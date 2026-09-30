"""Elaya NEW: Owner Inbox notifications feed + Delivery Photo Proof.
Covers:
  - Low-stock alert generated on POST /orders when a bouquet's stock crosses <=5
    (kind='stock', title '⚠️ Stock alert'), and dedup against unread alerts.
  - Notifications endpoints: GET /notifications, POST /notifications/{id}/read,
    POST /notifications/read-all.
  - Delivery Photo Proof: PATCH /owner/orders/{oid}/proof only by owning shop
    (403 otherwise), persists proof_photo, notifies customer (kind='order',
    title '📸 Delivery photo added'), and customer GET /orders/{id} sees it.
"""
import uuid
import time
import pytest
import requests
from conftest import BASE_URL, bearer


# ---------- helpers ----------
def _shop_of(api_client, owner_auth):
    r = api_client.get(f"{BASE_URL}/api/shops/mine", headers=bearer(owner_auth["access_token"]), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _create_low_stock_bouquet(api_client, owner_auth, stock: int, name_hint: str = ""):
    """Create a fresh bouquet with a specific stock level owned by owner_auth."""
    payload = {
        "name": f"TEST_LowStock_{name_hint}_{uuid.uuid4().hex[:6]}",
        "product_type": "bouquet",
        "price": 499,
        "stock": stock,
        "description": "for stock alert test",
        "image": "https://x/a.jpg",
        "images": ["https://x/a.jpg"],
    }
    r = api_client.post(f"{BASE_URL}/api/owner/products", json=payload, headers=bearer(owner_auth["access_token"]), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _place_order(api_client, customer_auth, product, qty=1, method="in_house"):
    item = {"product_id": product["id"], "shop_id": product["shop_id"], "name": product["name"],
            "image": product.get("image"), "unit_price": product["price"], "quantity": qty}
    payload = {
        "items": [item],
        "contact_name": "TEST Buyer",
        "contact_phone": "0917-000-0001",
        "delivery_method": method,
        "delivery_address": "TEST Addr" if method != "pickup" else "Pickup",
        "payment_method": "cod",
    }
    if method == "in_house":
        payload["delivery_lat"] = 14.35
        payload["delivery_lng"] = 121.09
    r = api_client.post(f"{BASE_URL}/api/orders", json=payload, headers=bearer(customer_auth["access_token"]), timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _delete_product(api_client, owner_auth, pid):
    api_client.delete(f"{BASE_URL}/api/owner/products/{pid}", headers=bearer(owner_auth["access_token"]), timeout=15)


# ---------- Feature: Low-stock alert notifications ----------
class TestLowStockAlert:
    def test_stock_crossing_threshold_creates_owner_alert(self, api_client, owner_auth, customer_auth):
        # Create product with 6 stock; ordering 2 drops it to 4 (crosses threshold 5)
        prod = _create_low_stock_bouquet(api_client, owner_auth, stock=6, name_hint="cross")
        try:
            _place_order(api_client, customer_auth, prod, qty=2)
            notifs = api_client.get(f"{BASE_URL}/api/notifications",
                                    headers=bearer(owner_auth["access_token"]), timeout=15).json()
            stock_notifs = [n for n in notifs if n.get("kind") == "stock" and n.get("product_id") == prod["id"]]
            assert stock_notifs, f"No stock alert for product {prod['id']} in {[n.get('title') for n in notifs][:10]}"
            n = stock_notifs[0]
            assert "Stock alert" in n["title"], n["title"]
            assert prod["name"] in n["body"]
            assert n["read"] is False
            # after=4 → "low on stock"
            assert "low on stock" in n["body"] or "out of stock" in n["body"]
        finally:
            _delete_product(api_client, owner_auth, prod["id"])

    def test_out_of_stock_message(self, api_client, owner_auth, customer_auth):
        # Create product with 1 stock; ordering 1 drops it to 0 → "out of stock" label
        prod = _create_low_stock_bouquet(api_client, owner_auth, stock=1, name_hint="oos")
        try:
            _place_order(api_client, customer_auth, prod, qty=1)
            notifs = api_client.get(f"{BASE_URL}/api/notifications",
                                    headers=bearer(owner_auth["access_token"]), timeout=15).json()
            match = [n for n in notifs if n.get("kind") == "stock" and n.get("product_id") == prod["id"]]
            assert match, "no stock alert for out-of-stock product"
            assert "out of stock" in match[0]["body"], match[0]["body"]
        finally:
            _delete_product(api_client, owner_auth, prod["id"])

    def test_stock_alert_deduped_while_unread(self, api_client, owner_auth, customer_auth):
        # Create product with 7 stock; two consecutive orders both crossing should
        # not produce two unread alerts.
        prod = _create_low_stock_bouquet(api_client, owner_auth, stock=7, name_hint="dedup")
        try:
            _place_order(api_client, customer_auth, prod, qty=3)  # -> 4 (cross)
            _place_order(api_client, customer_auth, prod, qty=1)  # -> 3 (still low, dedup)
            notifs = api_client.get(f"{BASE_URL}/api/notifications",
                                    headers=bearer(owner_auth["access_token"]), timeout=15).json()
            match = [n for n in notifs if n.get("kind") == "stock" and n.get("product_id") == prod["id"] and not n["read"]]
            assert len(match) == 1, f"expected 1 unread stock alert, got {len(match)}"
        finally:
            _delete_product(api_client, owner_auth, prod["id"])


# ---------- Feature: Notifications endpoints ----------
class TestNotificationsFeed:
    def test_list_and_read_flow(self, api_client, owner_auth, customer_auth):
        # Guarantee at least one unread notif by placing an order that crosses stock
        prod = _create_low_stock_bouquet(api_client, owner_auth, stock=6, name_hint="feed")
        try:
            _place_order(api_client, customer_auth, prod, qty=2)
            oh = bearer(owner_auth["access_token"])
            notifs = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
            assert isinstance(notifs, list) and notifs, "notifications list must be non-empty"
            # Response must NOT include mongo _id and MUST include fields consumed by UI
            for n in notifs[:5]:
                assert "_id" not in n
                for k in ("id", "kind", "title", "body", "read", "created_at"):
                    assert k in n, f"missing {k} in notification"
            # Sort by created_at desc
            times = [n["created_at"] for n in notifs]
            assert times == sorted(times, reverse=True), "notifications must be newest-first"

            target = next((n for n in notifs if not n["read"]), None)
            assert target, "expected an unread notification"
            r = api_client.post(f"{BASE_URL}/api/notifications/{target['id']}/read", headers=oh, timeout=15)
            assert r.status_code == 200
            after = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
            hit = next((n for n in after if n["id"] == target["id"]), None)
            assert hit and hit["read"] is True
        finally:
            _delete_product(api_client, owner_auth, prod["id"])

    def test_read_all(self, api_client, owner_auth, customer_auth):
        # Create some unread stock notifs
        prod = _create_low_stock_bouquet(api_client, owner_auth, stock=6, name_hint="readall")
        try:
            _place_order(api_client, customer_auth, prod, qty=2)
            oh = bearer(owner_auth["access_token"])
            pre = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
            assert any(not n["read"] for n in pre), "need at least one unread before read-all"
            r = api_client.post(f"{BASE_URL}/api/notifications/read-all", headers=oh, timeout=15)
            assert r.status_code == 200
            post = api_client.get(f"{BASE_URL}/api/notifications", headers=oh, timeout=15).json()
            assert all(n["read"] for n in post), "all notifications must be read after read-all"
        finally:
            _delete_product(api_client, owner_auth, prod["id"])

    def test_notifications_are_user_scoped(self, api_client, owner_auth, customer_auth):
        oh_notifs = api_client.get(f"{BASE_URL}/api/notifications",
                                   headers=bearer(owner_auth["access_token"]), timeout=15).json()
        ch_notifs = api_client.get(f"{BASE_URL}/api/notifications",
                                   headers=bearer(customer_auth["access_token"]), timeout=15).json()
        # Any owner stock notifs must not be present in customer's feed
        owner_stock_ids = {n["id"] for n in oh_notifs if n.get("kind") == "stock"}
        customer_ids = {n["id"] for n in ch_notifs}
        leaked = owner_stock_ids & customer_ids
        assert not leaked, f"stock notifs leaked across users: {leaked}"


# ---------- Feature: Delivery Photo Proof ----------
class TestDeliveryProof:
    def _make_delivery_order(self, api_client, customer_auth, owner_auth):
        # Reuse an approved-owner bouquet
        r = api_client.get(f"{BASE_URL}/api/products", params={"product_type": "bouquet"}, timeout=15)
        prods = r.json()
        shop = _shop_of(api_client, owner_auth)
        candidates = [p for p in prods if p["shop_id"] == shop["id"] and (p.get("stock") or 0) > 0]
        assert candidates, "owner shop has no in-stock bouquets"
        return _place_order(api_client, customer_auth, candidates[0], qty=1, method="in_house")

    def test_owner_uploads_proof_persists_and_notifies_customer(self, api_client, owner_auth, customer_auth):
        order = self._make_delivery_order(api_client, customer_auth, owner_auth)
        oid = order["id"]
        photo = f"https://example.com/proof/{uuid.uuid4().hex}.jpg"
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{oid}/proof",
                             json={"photo_url": photo}, headers=bearer(owner_auth["access_token"]), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True and body.get("proof_photo") == photo

        # Customer GET must expose proof_photo
        got = api_client.get(f"{BASE_URL}/api/orders/{oid}",
                             headers=bearer(customer_auth["access_token"]), timeout=15).json()
        assert got.get("proof_photo") == photo
        assert got.get("proof_at"), "proof_at should be set"

        # Customer notified with kind='order' + title contains '📸 Delivery photo'
        ch = bearer(customer_auth["access_token"])
        # small retry loop in case of async fanout
        found = None
        for _ in range(5):
            notifs = api_client.get(f"{BASE_URL}/api/notifications", headers=ch, timeout=15).json()
            found = next((n for n in notifs if n.get("order_id") == oid and "Delivery photo" in n.get("title", "")), None)
            if found: break
            time.sleep(0.5)
        assert found, "customer did not receive delivery-proof notification"
        assert found["kind"] == "order"

    def test_proof_forbidden_for_other_owner(self, api_client, owner_auth, owner2_auth, customer_auth):
        order = self._make_delivery_order(api_client, customer_auth, owner_auth)
        # owner2 does NOT own this order's shop
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/proof",
                             json={"photo_url": "https://x/y.jpg"},
                             headers=bearer(owner2_auth["access_token"]), timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_proof_requires_owner_role(self, api_client, owner_auth, customer_auth):
        order = self._make_delivery_order(api_client, customer_auth, owner_auth)
        # Customer role should be rejected (require('flower_owner'))
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/proof",
                             json={"photo_url": "https://x/y.jpg"},
                             headers=bearer(customer_auth["access_token"]), timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_proof_validation_rejects_empty(self, api_client, owner_auth, customer_auth):
        order = self._make_delivery_order(api_client, customer_auth, owner_auth)
        r = api_client.patch(f"{BASE_URL}/api/owner/orders/{order['id']}/proof",
                             json={"photo_url": ""},
                             headers=bearer(owner_auth["access_token"]), timeout=15)
        assert r.status_code == 422
