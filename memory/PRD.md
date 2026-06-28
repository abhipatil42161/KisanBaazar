# KisanBaazar — Product Requirements Document

## Problem Statement
Build a modern, secure, scalable, multilingual agriculture marketplace named **KisanBaazar** connecting Indian farmers directly with local, national, and international buyers, eliminating middlemen and providing transparent pricing.

## Architecture (as built)
- **Frontend**: React 19 + Tailwind + Shadcn UI + Framer Motion + react-router-dom 7
- **Backend**: FastAPI + Motor (async MongoDB)
- **Auth**: JWT (email/password) + Emergent-managed Google OAuth
- **AI**: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) via `emergentintegrations` + EMERGENT_LLM_KEY
- **Payments**: MOCK Razorpay (UPI/Card/Netbanking/Wallet methods shown; payment auto-confirmed)

## User Personas
- **Farmer** — lists products, manages inventory, tracks orders, gets AI price predictions
- **Buyer** — browses, filters, adds to cart, places orders, bids on auctions
- **Exporter** — discovers export-ready produce, manages shipments
- **Admin** — platform stats, all orders/users oversight

## Core Requirements (static)
1. Multi-role auth (4 roles)
2. Product catalog with 17 categories, filters (organic, export, auction, category, state, search)
3. Cart + Checkout with MOCK Razorpay
4. AI chat assistant (Claude Sonnet 4.5, streaming SSE)
5. AI price prediction for farmers
6. Auction system with bidding
7. Multi-lingual UI (16 languages, English/Hindi/Marathi fully translated)
8. Dark/Light theme toggle
9. Wishlist
10. Role-based dashboards (Farmer, Buyer, Exporter, Admin)

## Implemented (2026-02-Feb-27)
- ✅ Backend API (24 endpoints under `/api`)
- ✅ MongoDB models (User, Product, Order, Bid, Wishlist, ChatMessage)
- ✅ JWT auth + Emergent Google OAuth flow + session cookie
- ✅ Seeded demo data (3 users, 12 realistic products)
- ✅ Frontend: Home (hero, categories, featured, schemes, success stories, testimonials)
- ✅ Products listing + filters sidebar + Product detail with auction bidding
- ✅ Cart + Checkout with MOCK Razorpay payment
- ✅ Login/Register with role selection + Google OAuth button
- ✅ Dashboards: Farmer (with AI price predict + product CRUD), Buyer, Admin, Exporter
- ✅ AI Chat floating button with streaming Claude responses
- ✅ Language switcher (16 langs) + Dark/Light theme
- ✅ All UI uses Outfit (headings) + Work Sans (body), green/white organic theme

## Refactor — Phase A (2026-02-Feb-28)
- ✅ FarmerDashboard.jsx (217 LOC) split into 4 sub-components + 1 hook (each <120 LOC)
  - `/components/farmer/FarmerStats.jsx`, `FarmerListings.jsx`, `FarmerOrders.jsx`, `AddProductDialog.jsx`
  - `/hooks/useFarmerData.js` (data loader with `reload` exposed)
- ✅ AIChat.jsx split into `chat/ChatHeader.jsx`, `MessageList.jsx`, `MessageInput.jsx`
- ✅ Try/catch added to delete-listing handler
- ✅ DialogDescription added to AddProductDialog (a11y)
- ✅ Regression tested: backend pytest 14/14, frontend E2E 100% (iteration_8.json)

## Backlog (P1)
- **Phase C — Auth security migration**: localStorage → httpOnly cookies + CSRF (next priority per user)
- **Phase B — Continue splitting**: Home.jsx, Products.jsx, ProductDetail.jsx, Checkout.jsx
- Real Razorpay integration (replace MOCK with actual `razorpay-python` SDK)
- Image upload (object storage) instead of URL paste
- AI image quality check, AI disease detection
- WhatsApp/SMS notifications (Twilio)
- Aadhaar OTP login
- Live chat between buyer-farmer
- Map integration (Google Maps for delivery)
- Logistics: truck booking, cold storage
- Invoice PDF / GST integration
- Ratings & reviews
- PWA + offline support

## Backlog (P2)
- Referral program, coupons, affiliate
- Blog/News module
- Government scheme dynamic feed
- Video calling
- Help center + support tickets

## Next Action Items
1. **Phase C** — Migrate auth from `localStorage` to `httpOnly` cookies + CSRF tokens
2. **Phase B** — Continue component split (Home, Products, ProductDetail, Checkout)
3. Plug in real Razorpay keys when user provides them
4. Add image upload via object storage
5. Implement ratings/reviews
