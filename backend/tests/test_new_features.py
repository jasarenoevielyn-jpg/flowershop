"""Elaya NEW features tests: live tracking simulation, stock decrement on order,
rider location override, and PUT /owner/products preserving images[]."""
import time
import uuid
import pytest
import requests
from conftest import BASE_URL, bearer


def _seeded_shop_ids(api_client, *auths):
    ids = []
    for a in auths:
        h = bearer(a["access_token"])
        s = api_client.get(f"{BASE_URL}/api/shops/mine", headers=h, timeout=15)
        if s.status_code == 200:
            ids.append(s.json()["id"])
    return ids


def _pick_bouquet(api_client, shop_ids):
    prods = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15).json()
    filtered = [p for p in prods if p["shop_id"] in shop_ids]
    assert filtered, "No bouquet from seeded owners"
    return filtered[0]


def _new_in_house_order(api_client, customer_auth, product):
    payload = {
        "items": [{"product_id": product["id"], "shop_id": product["shop_id"], "name": product["name"],
                   "image": product.get("image"), "unit_price": product["price"], "quantity": 1}],
        "contact_name": "TEST Buyer",
        "contact_phone": "0917-000-0001",
        "delivery_method": "in_house",
        "delivery_address": "TEST Tracking Addr",
        "delivery_lat": 14.35, "delivery_lng": 121.09,
        "payment_method": "cod",
    }
    ch = bearer(customer_auth["access_token"])
    r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=ch, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _owning_owner(api_client, order, *auths):
    for oa in auths:
        oh = bearer(oa["access_token"])
        orders = api_client.get(f"{BASE_URL}/api/owner/orders", headers=oh, timeout=15).json()
        if any(o["id"] == order["id"] for o in orders):
            return oa
    return None


# ---------- Feature 1: Live tracking ----------
class TestLiveTracking:
    def test_tracking_pending_in_house_is_stationary(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_ids = _seeded_shop_ids(api_client, owner_auth, owner2_auth)
        prod = _pick_bouquet(api_client, shop_ids)
        order = _new_in_house_order(api_client, customer_auth, prod)
        r = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("lat", "lng", "dest_lat", "dest_lng", "start_lat", "start_lng", "moving", "progress", "eta_min"):
            assert k in d, f"missing {k}"
        assert d["moving"] is False
        assert d["progress"] == 0
        # Sits at shop start
        assert d["lat"] == d["start_lat"]
        assert d["lng"] == d["start_lng"]
        pytest.track_order_id = order["id"]
        pytest.track_dest = (d["dest_lat"], d["dest_lng"])
        pytest.track_start = (d["start_lat"], d["start_lng"])

    def test_tracking_moves_after_out_for_delivery(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_ids = _seeded_shop_ids(api_client, owner_auth, owner2_auth)
        prod = _pick_bouquet(api_client, shop_ids)
        order = _new_in_house_order(api_client, customer_auth, prod)
        owning = _owning_owner(api_client, order, owner_auth, owner2_auth)
        assert owning, "Could not identify owning owner"
        oh = bearer(owning["access_token"])
        # advance
        for st in ("confirmed", "preparing", "ready_for_delivery", "out_for_delivery"):
            r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/status",
                                 json={"status": st}, headers=oh, timeout=15)
            assert r.status_code == 200, f"{st}: {r.text}"
        # first sample
        r1 = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert r1["moving"] is True, r1
        p1 = r1["progress"]
        assert 0 <= p1 <= 1.0
        # sleep a few seconds and assert progress increased (simulation runs at ~1/480 per sec)
        time.sleep(6)
        r2 = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert r2["moving"] is True
        assert r2["progress"] > p1, f"progress did not advance: {p1} -> {r2['progress']}"
        # position moved
        assert (r2["lat"], r2["lng"]) != (r1["lat"], r1["lng"])
        assert r2["eta_min"] >= 1

    def test_pickup_tracking_not_moving(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_ids = _seeded_shop_ids(api_client, owner_auth, owner2_auth)
        prod = _pick_bouquet(api_client, shop_ids)
        pl = {"items": [{"product_id": prod["id"], "shop_id": prod["shop_id"], "name": prod["name"],
                         "image": prod.get("image"), "unit_price": prod["price"], "quantity": 1}],
              "contact_name": "TEST Buyer", "contact_phone": "0917-000-0001",
              "delivery_method": "pickup", "delivery_address": "Pickup",
              "payment_method": "cod"}
        ch = bearer(customer_auth["access_token"])
        order = api_client.post(f"{BASE_URL}/api/orders", json=pl, headers=ch, timeout=20).json()
        d = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert d["moving"] is False
        assert d["method"] == "pickup"

    def test_rider_manual_overrides_simulation(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_ids = _seeded_shop_ids(api_client, owner_auth, owner2_auth)
        prod = _pick_bouquet(api_client, shop_ids)
        order = _new_in_house_order(api_client, customer_auth, prod)
        owning = _owning_owner(api_client, order, owner_auth, owner2_auth)
        oh = bearer(owning["access_token"])
        for st in ("confirmed", "preparing", "ready_for_delivery", "out_for_delivery"):
            r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/status",
                                 json={"status": st}, headers=oh, timeout=15)
            assert r.status_code == 200
        # push manual rider location — must override simulated position
        MANUAL = {"lat": 14.4111, "lng": 121.0111}
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/rider",
                             json=MANUAL, headers=oh, timeout=15)
        assert r.status_code == 200
        d = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert abs(d["lat"] - MANUAL["lat"]) < 1e-6
        assert abs(d["lng"] - MANUAL["lng"]) < 1e-6
        assert d["moving"] is True

    def test_tracking_public_no_auth_required(self, api_client):
        oid = getattr(pytest, "track_order_id", None)
        assert oid, "prior test did not set order id"
        s = requests.Session()  # no auth header
        r = s.get(f"{BASE_URL}/api/orders/{oid}/tracking", timeout=15)
        assert r.status_code == 200

    def test_tracking_404_for_unknown(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/orders/does-not-exist-xxx/tracking", timeout=15)
        assert r.status_code == 404


# ---------- Feature 2: Stock decrement on order ----------
class TestStockDecrement:
    def test_ordering_decrements_stock(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_ids = _seeded_shop_ids(api_client, owner_auth, owner2_auth)
        prod = _pick_bouquet(api_client, shop_ids)
        pid = prod["id"]
        before = api_client.get(f"{BASE_URL}/api/products/{pid}", timeout=15).json()["stock"]
        assert before is not None
        qty = 2
        payload = {
            "items": [{"product_id": pid, "shop_id": prod["shop_id"], "name": prod["name"],
                       "image": prod.get("image"), "unit_price": prod["price"], "quantity": qty}],
            "contact_name": "TEST Buyer",
            "contact_phone": "0917-000-0001",
            "delivery_method": "in_house",
            "delivery_address": "TEST Stock",
            "delivery_lat": 14.34, "delivery_lng": 121.08,
            "payment_method": "cod",
        }
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=ch, timeout=20)
        assert r.status_code == 200, r.text
        after = api_client.get(f"{BASE_URL}/api/products/{pid}", timeout=15).json()["stock"]
        assert after == before - qty, f"stock should drop by {qty}: {before} -> {after}"


# ---------- Feature 3: Restock preserves images[] ----------
class TestRestockPreservesImages:
    def test_put_product_preserves_images(self, api_client, owner_auth):
        oh = bearer(owner_auth["access_token"])
        # create a product with 3 images
        imgs = ["https://x/a.jpg", "https://x/b.jpg", "https://x/c.jpg"]
        create_payload = {
            "name": f"TEST_Restock_{uuid.uuid4().hex[:5]}",
            "price": 500, "stock": 10,
            "description": "orig desc",
            "images": imgs,
        }
        c = api_client.post(f"{BASE_URL}/api/owner/products", json=create_payload, headers=oh, timeout=15)
        assert c.status_code == 200, c.text
        prod = c.json()
        assert prod["images"] == imgs
        pid = prod["id"]

        # Simulate the Restock modal: send full body (as the FE does) with stock bumped
        put_payload = {
            "name": prod["name"], "category": prod.get("category"),
            "description": prod.get("description"), "image": prod.get("image"),
            "images": prod["images"], "price": prod["price"],
            "stock": 50, "availability": prod.get("availability", True),
            "colors": prod.get("colors"), "flowers_included": prod.get("flowers_included"),
            "number_of_flowers": prod.get("number_of_flowers"),
            "wrapping": prod.get("wrapping"), "ribbon": prod.get("ribbon"),
            "style": prod.get("style"),
        }
        u = api_client.put(f"{BASE_URL}/api/owner/products/{pid}", json=put_payload, headers=oh, timeout=15)
        assert u.status_code == 200, u.text
        # GET verify: stock updated and images preserved (multi-angle 360 not wiped)
        g = api_client.get(f"{BASE_URL}/api/products/{pid}", timeout=15).json()
        assert g["stock"] == 50
        assert g["images"] == imgs, f"images were altered: {g['images']}"
        assert g["image"] == imgs[0]

        # cleanup
        api_client.delete(f"{BASE_URL}/api/owner/products/{pid}", headers=oh, timeout=15)
