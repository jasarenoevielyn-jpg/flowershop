"""Elaya backend tests: auth, shop application/approval, uploads,
products (bouquet + 360), shops/GPS, orders + delivery methods, payments
(COD + PayMongo GCash), notifications, admin flows, role enforcement."""
import io
import uuid
import pytest
import requests
from conftest import BASE_URL, bearer


# ---------- Health ----------
class TestHealth:
    def test_root(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("message") == "Elaya API"


# ---------- Auth ----------
class TestAuth:
    def test_login_admin(self, admin_auth):
        assert admin_auth["user"]["role"] == "admin"

    def test_login_customer(self, customer_auth):
        assert customer_auth["user"]["role"] == "customer"

    def test_login_owner_approved(self, owner_auth):
        assert owner_auth["user"]["role"] == "flower_owner"

    def test_login_pending_owner(self, pending_auth):
        assert pending_auth["user"]["role"] == "flower_owner"

    def test_login_invalid(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login",
                            json={"email": "admin@elaya.ph", "password": "bad"}, timeout=15)
        assert r.status_code == 401

    def test_register_new_customer(self, api_client):
        email = f"TEST_c_{uuid.uuid4().hex[:8]}@elaya.ph"
        r = api_client.post(f"{BASE_URL}/api/auth/register",
                            json={"name": "Test C", "email": email, "password": "TestPass1!"}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "customer"

    def test_register_new_shop_owner(self, api_client):
        email = f"TEST_o_{uuid.uuid4().hex[:8]}@elaya.ph"
        r = api_client.post(f"{BASE_URL}/api/auth/register",
                            json={"name": "Test O", "email": email, "password": "TestPass1!", "role": "flower_owner"}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["role"] == "flower_owner"
        # freshly registered owner has no shop
        h = bearer(data["access_token"])
        app_status = api_client.get(f"{BASE_URL}/api/owner/application", headers=h, timeout=15)
        assert app_status.status_code == 200
        assert app_status.json().get("status") == "none"
        pytest.new_owner_token = data["access_token"]


# ---------- Object storage upload ----------
class TestUpload:
    def test_upload_and_fetch(self, api_client, owner_auth):
        # 1x1 png
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
               b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
               b"\xc0\x00\x00\x00\x03\x00\x01\x9a|\xc4\x92\x00\x00\x00\x00IEND\xaeB`\x82")
        h = bearer(owner_auth["access_token"])
        files = {"file": ("test.png", png, "image/png")}
        # requests session default header sets content-type json; remove for multipart
        r = requests.post(f"{BASE_URL}/api/upload", files=files, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["url"].startswith("/api/files/")
        assert data["path"]
        # fetch the file
        f = requests.get(f"{BASE_URL}{data['url']}", timeout=30)
        assert f.status_code == 200
        assert f.content == png
        pytest.uploaded_url = f"{BASE_URL}{data['url']}"
        pytest.uploaded_path = data["path"]


# ---------- Shop application / approval flow ----------
class TestShopApplication:
    def test_pending_owner_sees_pending(self, api_client, pending_auth):
        h = bearer(pending_auth["access_token"])
        r = api_client.get(f"{BASE_URL}/api/owner/application", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "pending"

    def test_pending_owner_blocked_from_add_product(self, api_client, pending_auth):
        h = bearer(pending_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/owner/products",
                            json={"name": "X", "price": 10}, headers=h, timeout=15)
        assert r.status_code == 403

    def test_new_owner_submit_application_and_admin_approve_reject_reapply(self, api_client, admin_auth):
        # Register a brand-new owner just for this flow so we don't disturb seeded pending owner
        email = f"TEST_flow_{uuid.uuid4().hex[:6]}@elaya.ph"
        reg = api_client.post(f"{BASE_URL}/api/auth/register",
                              json={"name": "Flow", "email": email, "password": "TestPass1!", "role": "flower_owner"}, timeout=20)
        assert reg.status_code == 200
        owner_token = reg.json()["access_token"]
        oh = bearer(owner_token)

        # Submit application
        payload = {
            "shop_name": f"TEST_Shop_{uuid.uuid4().hex[:5]}",
            "description": "Test shop",
            "business_permit_url": getattr(pytest, "uploaded_url", "https://example.com/permit.jpg"),
            "location": "Test, Biñan",
            "lat": 14.34, "lng": 121.08,
            "owner_full_name": "Flow Owner",
            "contact_number": "09170001111",
            "owner_address": "Test Addr",
        }
        r = api_client.post(f"{BASE_URL}/api/owner/application", json=payload, headers=oh, timeout=20)
        assert r.status_code == 200, r.text
        shop = r.json()
        assert shop["status"] == "pending"
        assert shop["business_permit_url"] == payload["business_permit_url"]
        sid = shop["id"]

        # /shops/mine returns pending
        me = api_client.get(f"{BASE_URL}/api/shops/mine", headers=oh, timeout=15).json()
        assert me["status"] == "pending"

        # Admin sees it in /admin/shop-owners with owner_email + business_permit_url
        ah = bearer(admin_auth["access_token"])
        listing = api_client.get(f"{BASE_URL}/api/admin/shop-owners", headers=ah, timeout=15).json()
        found = [s for s in listing if s["id"] == sid]
        assert found, "New application not in admin listing"
        assert found[0]["owner_email"] == email.lower()
        assert found[0]["business_permit_url"] == payload["business_permit_url"]

        # Admin rejects
        r = api_client.patch(f"{BASE_URL}/api/admin/shop-owners/{sid}/reject",
                             json={"reason": "Test reject"}, headers=ah, timeout=15)
        assert r.status_code == 200
        me2 = api_client.get(f"{BASE_URL}/api/shops/mine", headers=oh, timeout=15).json()
        assert me2["status"] == "rejected"
        assert me2["reject_reason"] == "Test reject"

        # Owner re-applies -> back to pending
        payload2 = {**payload, "description": "Re-applied"}
        r = api_client.post(f"{BASE_URL}/api/owner/application", json=payload2, headers=oh, timeout=20)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

        # Admin approves
        r = api_client.patch(f"{BASE_URL}/api/admin/shop-owners/{sid}/approve",
                             headers=ah, timeout=15)
        assert r.status_code == 200
        me3 = api_client.get(f"{BASE_URL}/api/shops/mine", headers=oh, timeout=15).json()
        assert me3["status"] == "approved"

        # Now owner can add product
        prod = {"name": "TEST_Bouquet", "price": 500, "stock": 5,
                "images": ["https://x/a.jpg", "https://x/b.jpg", "https://x/c.jpg"]}
        r = api_client.post(f"{BASE_URL}/api/owner/products", json=prod, headers=oh, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["product_type"] == "bouquet"
        assert len(p["images"]) == 3

        # Owner receives notifications for approve/reject
        notifs = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
        kinds = [n["title"] for n in notifs]
        assert any("approved" in t.lower() for t in kinds), kinds
        assert any("rejected" in t.lower() for t in kinds), kinds


# ---------- Products ----------
class TestProducts:
    def test_bouquet_list_has_multi_angle_images(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        # at least one seeded bouquet has multiple images
        multi = [p for p in items if isinstance(p.get("images"), list) and len(p["images"]) >= 2]
        assert multi, "No bouquet with multi-angle images"
        pytest.bouquet = multi[0]

    def test_product_detail_contains_shop_delivery_methods(self, api_client):
        pid = pytest.bouquet["id"]
        r = api_client.get(f"{BASE_URL}/api/products/{pid}", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["shop"] is not None
        assert isinstance(d["shop"].get("delivery_methods"), list)


# ---------- Shops / GPS ----------
class TestShops:
    def test_list_shops_only_approved_and_sorted(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/shops", timeout=15)
        assert r.status_code == 200
        shops = r.json()
        assert shops
        assert all(s["status"] == "approved" for s in shops)
        assert all("distance_km" in s for s in shops)
        # sorted asc
        dists = [s["distance_km"] for s in shops]
        assert dists == sorted(dists)
        # 'Petal Grove' (pending) must NOT be listed
        assert not any(s["shop_name"] == "Petal Grove" for s in shops)

    def test_shops_with_gps_query(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/shops", params={"lat": 14.34, "lng": 121.08}, timeout=15)
        assert r.status_code == 200
        assert all("distance_km" in s for s in r.json())


# ---------- Orders + delivery methods ----------
class TestOrders:
    def _create_order(self, api_client, customer_auth, method, owner_shop_ids=None):
        products = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15).json()
        if owner_shop_ids:
            products = [p for p in products if p["shop_id"] in owner_shop_ids] or products
        p = products[0]
        payload = {
            "items": [{"product_id": p["id"], "shop_id": p["shop_id"], "name": p["name"],
                       "image": p.get("image"), "unit_price": p["price"], "quantity": 1}],
            "contact_name": "TEST Buyer",
            "contact_phone": "0917-000-0001",
            "delivery_method": method,
            "delivery_address": "TEST Addr",
            "delivery_lat": 14.34, "delivery_lng": 121.08,
            "payment_method": "cod",
        }
        h = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=h, timeout=20)
        assert r.status_code == 200, r.text
        return r.json()

    def test_create_in_house_and_flow(self, api_client, customer_auth, owner_auth, owner2_auth):
        # gather seeded owners' shop ids so we always order from a known owner
        seeded_shop_ids = []
        for oa in (owner_auth, owner2_auth):
            oh = bearer(oa["access_token"])
            s = api_client.get(f"{BASE_URL}/api/shops/mine", headers=oh, timeout=15)
            if s.status_code == 200:
                seeded_shop_ids.append(s.json()["id"])
        order = self._create_order(api_client, customer_auth, "in_house", owner_shop_ids=seeded_shop_ids)
        assert order["delivery_method"] == "in_house"
        assert order["status_flow"] == ["pending", "confirmed", "preparing", "ready_for_delivery", "out_for_delivery", "completed"]
        pytest.in_house_order_id = order["id"]
        pytest.in_house_shop_id = order["shop_ids"][0]
        # find owning owner
        for oa in (owner_auth, owner2_auth):
            oh = bearer(oa["access_token"])
            orders = api_client.get(f"{BASE_URL}/api/owner/orders", headers=oh, timeout=15).json()
            if any(o["id"] == order["id"] for o in orders):
                pytest.owning_auth = oa
                break
        assert getattr(pytest, "owning_auth", None)

    def test_create_third_party_flow(self, api_client, customer_auth):
        order = self._create_order(api_client, customer_auth, "third_party")
        assert order["delivery_method"] == "third_party"
        assert "handed_to_courier" in order["status_flow"]

    def test_create_pickup_flow(self, api_client, customer_auth):
        order = self._create_order(api_client, customer_auth, "pickup")
        assert order["delivery_method"] == "pickup"
        assert "ready_for_pickup" in order["status_flow"]

    def test_customer_get_mine_and_detail(self, api_client, customer_auth):
        h = bearer(customer_auth["access_token"])
        mine = api_client.get(f"{BASE_URL}/api/orders/mine", headers=h, timeout=15).json()
        assert any(o["id"] == pytest.in_house_order_id for o in mine)
        d = api_client.get(f"{BASE_URL}/api/orders/{pytest.in_house_order_id}", headers=h, timeout=15)
        assert d.status_code == 200

    def test_owner_advance_status_and_rider(self, api_client):
        oa = pytest.owning_auth
        h = bearer(oa["access_token"])
        oid = pytest.in_house_order_id
        for status_val in ["confirmed", "preparing", "ready_for_delivery", "out_for_delivery"]:
            r = api_client.patch(f"{BASE_URL}/api/owner/orders/{oid}/status",
                                 json={"status": status_val}, headers=h, timeout=15)
            assert r.status_code == 200, f"{status_val}: {r.text}"
            assert r.json()["status"] == status_val
        # invalid status rejected
        bad = api_client.patch(f"{BASE_URL}/api/owner/orders/{oid}/status",
                               json={"status": "ready_for_pickup"}, headers=h, timeout=15)
        assert bad.status_code == 400
        # rider location update
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{oid}/rider",
                             json={"lat": 14.35, "lng": 121.09}, headers=h, timeout=15)
        assert r.status_code == 200


# ---------- Payments ----------
class TestPayments:
    def test_cod_marks_pending_and_notifies_owner(self, api_client, customer_auth, owner_auth, owner2_auth):
        # create fresh order for COD from a seeded owner's shop
        seeded_shop_ids = []
        for oa in (owner_auth, owner2_auth):
            oh = bearer(oa["access_token"])
            s = api_client.get(f"{BASE_URL}/api/shops/mine", headers=oh, timeout=15)
            if s.status_code == 200:
                seeded_shop_ids.append(s.json()["id"])
        products = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15).json()
        products = [p for p in products if p["shop_id"] in seeded_shop_ids] or products
        p = products[0]
        pl = {"items": [{"product_id": p["id"], "shop_id": p["shop_id"], "name": p["name"],
                        "image": p.get("image"), "unit_price": p["price"], "quantity": 1}],
              "contact_name": "TEST Buyer", "contact_phone": "0917-000-0001",
              "delivery_method": "in_house", "delivery_address": "A", "payment_method": "cod"}
        ch = bearer(customer_auth["access_token"])
        order = api_client.post(f"{BASE_URL}/api/orders", json=pl, headers=ch, timeout=20).json()
        oid = order["id"]

        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/pay/cod", headers=ch, timeout=20)
        assert r.status_code == 200
        assert r.json()["payment_status"] == "cod_pending"

        # owner should have a notification about COD
        oa = pytest.owning_auth
        oh = bearer(oa["access_token"])
        notifs = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
        assert any(n.get("order_id") == oid and n.get("kind") == "order" for n in notifs), \
            "Owner did not receive COD notification"

    def test_gcash_creates_paymongo_intent(self, api_client, customer_auth):
        products = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15).json()
        p = products[0]
        pl = {"items": [{"product_id": p["id"], "shop_id": p["shop_id"], "name": p["name"],
                        "image": p.get("image"), "unit_price": p["price"], "quantity": 1}],
              "contact_name": "TEST Buyer", "contact_phone": "0917-000-0001",
              "delivery_method": "in_house", "delivery_address": "A", "payment_method": "gcash"}
        ch = bearer(customer_auth["access_token"])
        order = api_client.post(f"{BASE_URL}/api/orders", json=pl, headers=ch, timeout=20).json()
        oid = order["id"]
        r = api_client.post(f"{BASE_URL}/api/orders/{oid}/pay/gcash", headers=ch, timeout=40)
        # Either success with redirect, or PayMongo test may 502/500 if key rate-limited
        if r.status_code != 200:
            pytest.skip(f"PayMongo unavailable: {r.status_code} {r.text}")
        data = r.json()
        assert data.get("redirect_url", "").startswith("http")
        assert data.get("intent_id")

        # payment-status endpoint accessible; still unpaid
        ps = api_client.get(f"{BASE_URL}/api/orders/{oid}/payment-status", headers=ch, timeout=30)
        assert ps.status_code == 200
        assert ps.json()["payment_status"] in ("pending", "unpaid", "paid")


# ---------- Admin ----------
class TestAdmin:
    def test_overview_has_shop_counts(self, api_client, admin_auth):
        h = bearer(admin_auth["access_token"])
        r = api_client.get(f"{BASE_URL}/api/admin/overview", headers=h, timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ["shops_pending", "shops_approved", "shops_rejected",
                  "total_owners", "total_shops", "total_orders"]:
            assert k in d, f"Missing {k}"
        assert d["shops_approved"] >= 2

    def test_admin_orders_list(self, api_client, admin_auth):
        h = bearer(admin_auth["access_token"])
        r = api_client.get(f"{BASE_URL}/api/admin/orders", headers=h, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_toggle_user_status(self, api_client, admin_auth):
        email = f"TEST_tog_{uuid.uuid4().hex[:6]}@elaya.ph"
        reg = api_client.post(f"{BASE_URL}/api/auth/register",
                              json={"name": "T", "email": email, "password": "TestPass1!"}, timeout=15)
        assert reg.status_code == 200
        uid = reg.json()["user"]["id"]
        h = bearer(admin_auth["access_token"])
        r = api_client.patch(f"{BASE_URL}/api/admin/users/{uid}/status",
                             params={"new_status": "disabled"}, headers=h, timeout=15)
        assert r.status_code == 200
        li = api_client.post(f"{BASE_URL}/api/auth/login",
                             json={"email": email, "password": "TestPass1!"}, timeout=15)
        assert li.status_code == 403


# ---------- Role enforcement ----------
class TestRBAC:
    def test_customer_blocked_from_owner_endpoints(self, api_client, customer_auth):
        h = bearer(customer_auth["access_token"])
        r = api_client.post(f"{BASE_URL}/api/owner/products", json={"name": "X", "price": 10}, headers=h, timeout=15)
        assert r.status_code == 403
        r2 = api_client.get(f"{BASE_URL}/api/owner/orders", headers=h, timeout=15)
        assert r2.status_code == 403

    def test_customer_blocked_from_admin(self, api_client, customer_auth):
        h = bearer(customer_auth["access_token"])
        r = api_client.get(f"{BASE_URL}/api/admin/overview", headers=h, timeout=15)
        assert r.status_code == 403

    def test_owner_blocked_from_admin(self, api_client, owner_auth):
        h = bearer(owner_auth["access_token"])
        r = api_client.get(f"{BASE_URL}/api/admin/shop-owners", headers=h, timeout=15)
        assert r.status_code == 403
