# ELAYA — Product Requirements Document

## Original Problem Statement
Design and develop ELAYA, a mobile flower marketplace for Biñan, Laguna. Interactive 360° multi-photo bouquet view, GPS/Google-Maps based location + nearby shop discovery, route/logistics with 3 delivery options (In-House with live tracking, Third-Party, Pick-Up), GCash (PayMongo) + Cash-on-Delivery payments, shop owner registration with admin approval, vendor dashboard, inventory + low stock alerts, reorder favorites. Roles: Customer, Shop Owner, Admin. Simple email+password auth.

## Architecture
- Frontend: Expo Router (React Native), @tanstack/react-query, expo-image, react-native-gesture-handler + reanimated (360 viewer), react-native-webview (Leaflet map).
- Backend: FastAPI + Motor (MongoDB). JWT auth (bcrypt). Emergent Object Storage for uploads.
- Payments: PayMongo GCash (test) + COD. Reconciled via /payment-status polling.
- Env: backend/.env (MONGO_URL, DB_NAME, JWT_SECRET, PAYMONGO_SECRET_KEY, EMERGENT_LLM_KEY, APP_URL, INTEGRATION_PROXY_URL); frontend/.env (EXPO_PUBLIC_BACKEND_URL).

## User Personas
- Customer: browses bouquets, inspects 360°, orders, pays, tracks delivery, reorders favorites, reviews.
- Shop Owner (flower_owner): registers shop, awaits approval, manages bouquets (multi-angle photos), orders, delivery methods, sees low-stock alerts.
- Admin: approves/rejects shop owners, monitors users/shops/orders, overview metrics.

## Core Requirements (static)
- 360° multi-photo bouquet viewer (2–12 angles, swipe/drag/tap).
- Owner Android image upload (multipart via XHR — fixes "Unsupported FormDataPart").
- Customer dashboard displays main image + all angle images.
- Admin approval workflow; only approved owners sell.
- 3 delivery methods; in-house live rider tracking map.
- GCash + COD payments.

## Implemented (2026-06)
- Restored missing backend/.env & frontend/.env (imported repo) — app was fully down; now running.
- Verified end-to-end: upload → object storage → product images[] → retrieval; customer photo display; 360 viewer rotation; admin approval; orders + COD + GCash intent; live tracking.
- Seeded demo data (admin, customer, 2 approved + 1 pending owner, 4 bouquets).
- Cleaned leftover TEST_* products with placeholder image URLs.
- 37/37 backend pytest pass; frontend critical paths verified.

## Session (2026-06-30) — Env restore after GitHub re-import
- Repo re-import again dropped gitignored .env → backend crash-loop (KeyError: MONGO_URL), app blank on devices (this was the real cause behind "background not visible on mobile", upload errors, blank 360).
- Recreated backend/.env (MONGO_URL, DB_NAME, JWT_SECRET, PAYMONGO_SECRET_KEY=sk_test_..., ADMIN_SIGNUP_CODE=ELAYA-ADMIN-2026, EMERGENT_LLM_KEY) and frontend/.env (EXPO_PUBLIC_BACKEND_URL + packager vars).
- Verified: object storage upload+retrieval, 43/43 backend pytest, frontend renders all images + 360 badges, admin login.

## Session (2026-06-30b) — 5 feature additions
- Order Chat: per-order customer↔owner messaging (GET/POST /api/orders/{id}/messages + notifications, kind=chat). Shared OrderChat component + (customer)/chat/[id] & (owner)/chat/[id] routes. Entry buttons on Track & owner order detail.
- Delivery ETA: live mm:ss countdown card on customer Track during in-house out_for_delivery (driven by /tracking eta_min).
- Owner tracking visibility: owner order detail shows live status + ETA + address + rider coords + LiveTrackMap.
- Customer Completed: POST /api/orders/{id}/complete → status=completed, COD→paid, notifies owner; "I received my order" button + completed banner.
- Checkout mandatory contact: OrderIn now requires contact_name + contact_phone (422 if missing); checkout has Full Name (prefilled) + Phone fields with validation.
- Tested: 55/55 backend pytest, all UI flows OK.

## Session (2026-06-30c) — Owner Inbox + Delivery Proof
- Order Updates Feed: dedicated owner inbox (/(owner)/inbox) with unread badge, mark-all-read, tap-to-navigate; dashboard bell + "see all" link. Low-stock now emits kind=stock notifications (deduped) on stock-dropping orders alongside chat/paid/order alerts.
- Delivery Photo Proof: PATCH /api/owner/orders/{id}/proof (owner-only) stores proof_photo + notifies customer; owner order screen add-proof (camera on native, gallery fallback/web) with preview; customer Track shows the photo. Added CAMERA/photo/location perms to app.json.
- Fixed hooks-order bug in owner order detail (proofMut hoisted above early return).
- Tested: 65/65 backend pytest, all UI flows OK.

## Backlog / Remaining
- P1: Google Maps API key (user will add later) — currently Leaflet-based map UI.
- P2: Rotate360 skeleton loader on first frame; periodic TEST_* cleanup.
- P2: Real third-party (Lalamove/Grab) API integration (currently manual status flow).
