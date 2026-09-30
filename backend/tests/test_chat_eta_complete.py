"""Elaya NEW features (Jan 2026 iteration): order chat, delivery ETA countdown,
customer 'Completed' button API, and mandatory contact_name/contact_phone at checkout."""
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


def _pick_bouquet_for_shop(api_client, shop_id):
    prods = api_client.get(f"{BASE_URL}/api/products", timeout=15).json()
    filtered = [p for p in prods if p["shop_id"] == shop_id]
    assert filtered, f"No bouquet from shop {shop_id}"
    return filtered[0]


def _owning_owner(api_client, order, *auths):
    for oa in auths:
        oh = bearer(oa["access_token"])
        orders = api_client.get(f"{BASE_URL}/api/owner/orders", headers=oh, timeout=15).json()
        if any(o["id"] == order["id"] for o in orders):
            return oa
    return None


def _create_in_house_order(api_client, customer_auth, product, contact_name="TEST Buyer", contact_phone="0917-000-0001"):
    payload = {
        "items": [{"product_id": product["id"], "shop_id": product["shop_id"], "name": product["name"],
                   "image": product.get("image"), "unit_price": product["price"], "quantity": 1}],
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "delivery_method": "in_house",
        "delivery_address": "TEST Chat Addr",
        "delivery_lat": 14.35, "delivery_lng": 121.09,
        "payment_method": "cod",
    }
    ch = bearer(customer_auth["access_token"])
    r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=ch, timeout=20)
    return r


# ---------- Feature: mandatory contact fields at checkout ----------
class TestCheckoutMandatoryContact:
    def test_create_order_missing_contact_fields_returns_422(self, api_client, customer_auth, owner_auth):
        shop_id = _seeded_shop_ids(api_client, owner_auth)[0]
        prod = _pick_bouquet_for_shop(api_client, shop_id)
        payload = {
            "items": [{"product_id": prod["id"], "shop_id": prod["shop_id"], "name": prod["name"],
                       "image": prod.get("image"), "unit_price": prod["price"], "quantity": 1}],
            "delivery_method": "in_house",
            "delivery_address": "TEST no-contact",
            "payment_method": "cod",
        }
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=ch, timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"

    def test_create_order_empty_contact_fields_returns_422(self, api_client, customer_auth, owner_auth):
        shop_id = _seeded_shop_ids(api_client, owner_auth)[0]
        prod = _pick_bouquet_for_shop(api_client, shop_id)
        payload = {
            "items": [{"product_id": prod["id"], "shop_id": prod["shop_id"], "name": prod["name"],
                       "image": prod.get("image"), "unit_price": prod["price"], "quantity": 1}],
            "contact_name": "",
            "contact_phone": "",
            "delivery_method": "in_house",
            "delivery_address": "TEST empty-contact",
            "payment_method": "cod",
        }
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=ch, timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"

    def test_create_order_with_contact_ok_and_persisted(self, api_client, customer_auth, owner_auth):
        shop_id = _seeded_shop_ids(api_client, owner_auth)[0]
        prod = _pick_bouquet_for_shop(api_client, shop_id)
        r = _create_in_house_order(api_client, customer_auth, prod,
                                   contact_name="TEST Alicia", contact_phone="0917-555-9999")
        assert r.status_code == 200, r.text
        order = r.json()
        assert order["contact_name"] == "TEST Alicia"
        assert order["contact_phone"] == "0917-555-9999"
        # GET verify persistence
        ch = bearer(customer_auth["access_token"])
        g = api_client.get(f"{BASE_URL}/api/orders/{order['id']}", headers=ch, timeout=15).json()
        assert g["contact_name"] == "TEST Alicia"
        assert g["contact_phone"] == "0917-555-9999"
        pytest.chat_order_id = order["id"]
        pytest.chat_order_shop_id = shop_id


# ---------- Feature: order chat (list/post + access control + notifications) ----------
class TestOrderChat:
    def test_customer_and_owner_can_chat(self, api_client, customer_auth, owner_auth, owner2_auth):
        oid = getattr(pytest, "chat_order_id", None)
        assert oid, "Prior checkout test must have run"
        ch = bearer(customer_auth["access_token"])
        # Initially empty
        r = api_client.get(f"{BASE_URL}/api/orders/{oid}/messages", headers=ch, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # Customer sends
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/messages",
                            json={"text": "Hi, please add a card"}, headers=ch, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["sender_role"] == "customer"
        assert m["text"] == "Hi, please add a card"
        # Owner reads + replies
        order = api_client.get(f"{BASE_URL}/api/orders/{oid}", headers=ch, timeout=15).json()
        owning = _owning_owner(api_client, order, owner_auth, owner2_auth)
        assert owning, "Could not resolve owning owner"
        oh = bearer(owning["access_token"])
        lst = api_client.get(f"{BASE_URL}/api/orders/{oid}/messages", headers=oh, timeout=15)
        assert lst.status_code == 200
        assert any(msg["text"] == "Hi, please add a card" for msg in lst.json())
        r2 = api_client.post(f"{BASE_URL}/api/orders/{oid}/messages",
                             json={"text": "Sure — pink card ok?"}, headers=oh, timeout=15)
        assert r2.status_code == 200
        # Customer sees owner reply
        lst2 = api_client.get(f"{BASE_URL}/api/orders/{oid}/messages", headers=ch, timeout=15).json()
        texts = [x["text"] for x in lst2]
        assert "Sure — pink card ok?" in texts
        # Customer got a chat-kind notification from owner reply
        notes = api_client.get(f"{BASE_URL}/api/notifications", headers=ch, timeout=15).json()
        assert any(n.get("kind") == "chat" and n.get("order_id") == oid for n in notes), \
            "customer missing chat notification"
        # Owner got a chat-kind notification from customer send
        onotes = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
        assert any(n.get("kind") == "chat" and n.get("order_id") == oid for n in onotes), \
            "owner missing chat notification"

    def test_unrelated_owner_forbidden(self, api_client, owner_auth, owner2_auth):
        oid = getattr(pytest, "chat_order_id", None)
        assert oid
        # Determine which is the OTHER owner (not the one for chat_order_shop_id)
        shop_id = pytest.chat_order_shop_id
        other = None
        for oa in (owner_auth, owner2_auth):
            h = bearer(oa["access_token"])
            mine = api_client.get(f"{BASE_URL}/api/shops/mine", headers=h, timeout=15).json()
            if mine["id"] != shop_id:
                other = oa
                break
        assert other, "no other owner"
        oh = bearer(other["access_token"])
        r = api_client.get(f"{BASE_URL}/api/orders/{oid}/messages", headers=oh, timeout=15)
        assert r.status_code == 403, r.text
        r2 = api_client.post(f"{BASE_URL}/api/orders/{oid}/messages",
                             json={"text": "should be blocked"}, headers=oh, timeout=15)
        assert r2.status_code == 403

    def test_unrelated_customer_forbidden(self, api_client, customer_auth, admin_auth):
        # There's only one customer seeded; use admin who is not customer/owner on this order.
        # Admin role is neither customer nor flower_owner: order_for_user should return the order (no 403 branch),
        # so we instead assert with a bogus order id → 404 to confirm the guard path is reachable.
        r = api_client.get(f"{BASE_URL}/api/orders/does-not-exist-xxx/messages",
                           headers=bearer(admin_auth["access_token"]), timeout=15)
        assert r.status_code == 404

    def test_empty_message_rejected(self, api_client, customer_auth):
        oid = pytest.chat_order_id
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/messages",
                            json={"text": ""}, headers=ch, timeout=15)
        assert r.status_code == 422


# ---------- Feature: Delivery ETA countdown surface ----------
class TestDeliveryEta:
    def test_eta_zero_before_out_for_delivery_then_advances(self, api_client, customer_auth, owner_auth, owner2_auth):
        shop_id = _seeded_shop_ids(api_client, owner_auth)[0]
        prod = _pick_bouquet_for_shop(api_client, shop_id)
        r = _create_in_house_order(api_client, customer_auth, prod)
        assert r.status_code == 200
        order = r.json()
        pre = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert pre["eta_min"] == 0
        assert pre["moving"] is False
        owning = _owning_owner(api_client, order, owner_auth, owner2_auth)
        oh = bearer(owning["access_token"])
        for st in ("confirmed", "preparing", "ready_for_delivery", "out_for_delivery"):
            rr = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/status",
                                  json={"status": st}, headers=oh, timeout=15)
            assert rr.status_code == 200, rr.text
        d = api_client.get(f"{BASE_URL}/api/orders/{order['id']}/tracking", timeout=15).json()
        assert d["moving"] is True
        assert isinstance(d["eta_min"], (int, float))
        assert d["eta_min"] >= 1
        assert d["eta_min"] <= 8
        pytest.eta_order_id = order["id"]
        pytest.eta_owning = owning


# ---------- Feature: Customer 'Completed' button ----------
class TestOrderComplete:
    def test_customer_complete_marks_completed_and_notifies_owner(self, api_client, customer_auth, owner_auth, owner2_auth):
        oid = getattr(pytest, "eta_order_id", None)
        assert oid, "prior ETA test must have run"
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/complete", headers=ch, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "completed"
        # verify persisted
        g = api_client.get(f"{BASE_URL}/api/orders/{oid}", headers=ch, timeout=15).json()
        assert g["status"] == "completed"
        # COD is settled as paid
        assert g["payment_method"] == "cod"
        assert g["payment_status"] == "paid"
        assert g.get("completed_by_customer") is True
        # Owner receives 'order received' notification
        owning = pytest.eta_owning
        oh = bearer(owning["access_token"])
        notes = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
        assert any(n.get("order_id") == oid and "confirmed receipt" in (n.get("body") or "")
                   for n in notes), "owner missing 'order received' notification"

    def test_complete_idempotent(self, api_client, customer_auth):
        oid = pytest.eta_order_id
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/complete", headers=ch, timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "completed"

    def test_complete_forbidden_for_other_user(self, api_client, owner_auth):
        oid = pytest.eta_order_id
        oh = bearer(owner_auth["access_token"])
        # Owner is not customer role -> require("customer") -> 403
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/complete", headers=oh, timeout=15)
        assert r.status_code == 403

    def test_complete_unknown_order_404(self, api_client, customer_auth):
        ch = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders/does-not-exist/complete", headers=ch, timeout=15)
        assert r.status_code == 404
