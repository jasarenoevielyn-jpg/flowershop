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

## Backlog / Remaining
- P1: Google Maps API key (user will add later) — currently Leaflet-based map UI.
- P2: Rotate360 skeleton loader on first frame; periodic TEST_* cleanup.
- P2: Real third-party (Lalamove/Grab) API integration (currently manual status flow).
