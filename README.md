# KisanBaazar — Agriculture Marketplace

Modern, secure, multilingual marketplace connecting Indian farmers to local, national, and international buyers. React + FastAPI + MongoDB.

## Quick start (local)

```bash
# 1. Backend
cp backend/.env.example backend/.env   # fill in real values
pip install -r backend/requirements.txt
sudo supervisorctl restart backend

# 2. Frontend
yarn install --cwd frontend
sudo supervisorctl restart frontend

# 3. Seed demo data (optional)
python backend/seed/seed_data.py
```

## Cloudinary image upload

The marketplace uses **Cloudinary** with the signed direct-upload pattern: the
frontend never sees the API secret, but uploads the file straight to Cloudinary
using a short-lived signature minted by FastAPI.

### Configuration

Set these in `backend/.env` (see `backend/.env.example`):

```ini
CLOUDINARY_CLOUD_NAME=...      # from https://cloudinary.com/console
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...       # backend-only; never expose to client
CLOUDINARY_UPLOAD_FOLDER=kisanbaazar/products
```

After updating `.env`, restart the backend: `sudo supervisorctl restart backend`.

### Endpoints

| Method | Path                          | Auth   | Purpose                                                  |
|--------|-------------------------------|--------|----------------------------------------------------------|
| GET    | `/api/cloudinary/signature`   | Cookie | Returns `{signature, timestamp, api_key, cloud_name, folder, max_bytes, allowed_formats}`. |
| DELETE | `/api/cloudinary/image`       | Cookie + CSRF | Deletes one asset by `public_id`. Owner or admin only. |
| DELETE | `/api/products/{pid}`         | Cookie + CSRF | Cascade-deletes all Cloudinary assets attached to the product. |

### Frontend (`<ImageUploader />`)

- Drag-and-drop, multi-file
- Max 10 images per product
- Accepted: `image/jpeg`, `image/jpg`, `image/png`, `image/webp`
- 10 MB hard cap (validated client-side + Cloudinary upload preset)
- Live per-file progress + cancel
- Sanitised filenames (`a-zA-Z0-9._-` only, NFKD-normalised, ≤80 chars)
- Stored metadata per image: `{ secure_url, public_id, width, height }`
- Delivery URLs auto-inject `f_auto,q_auto` via `src/lib/images.js → imgUrl()`

### Database schema

```js
// products.images is an array of:
{
  secure_url: "https://res.cloudinary.com/<cloud>/image/upload/v.../kisanbaazar/products/<pid>.jpg",
  public_id:  "kisanbaazar/products/<pid>",
  width:      1600,
  height:     1200
}
// Legacy seed data may also hold plain string URLs — both formats are
// accepted on write; `imgUrl()` normalises at read time.
```

### Security

- API secret loaded only from `backend/.env`, never sent to the client
- Signed payloads include `folder` constrained to `kisanbaazar/*` prefix — attackers can't sign arbitrary paths
- Filenames sanitised before upload
- Owner-only delete: only the listing farmer (or admin) can delete a public_id attached to their products
- Cascade delete: product DELETE removes all attached Cloudinary assets and detaches them from any referencing documents

## Razorpay payment integration

Real Razorpay is wired up via the **server-side order creation + client checkout
+ signature verification** pattern. Secrets never leave the backend.

### Configuration

Add to `backend/.env` (see `backend/.env.example`):

```ini
RAZORPAY_KEY_ID=rzp_test_xxx        # public key id (frontend uses this)
RAZORPAY_KEY_SECRET=xxxxxxxx        # backend-only — used to sign & verify
RAZORPAY_WEBHOOK_SECRET=xxxxxxxx    # optional, only set if webhook configured
```

Leave **both** `KEY_ID` and `KEY_SECRET` blank to keep the MOCK payment flow
(useful for dev environments without Razorpay account access). After updating
`.env`, restart backend: `sudo supervisorctl restart backend`.

Get test/live keys from the [Razorpay Dashboard → API Keys](https://dashboard.razorpay.com/app/keys).

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/payments/config` | Public | Returns `{enabled, key_id}` — never exposes secret. |
| POST | `/api/orders` | Cookie + CSRF | Creates the order; for non-COD methods also creates a Razorpay order and returns `razorpay_order_id` + `razorpay_amount_paise`. |
| POST | `/api/orders/{oid}/verify` | Cookie + CSRF | Verifies Razorpay's `razorpay_signature` from the success handler; marks order `paid` + `confirmed`. Invalid signatures mark it `failed`. |
| POST | `/api/orders/{oid}/pay` | Cookie + CSRF | Mock-pay fallback. Allowed when Razorpay is disabled OR when `payment_method == "cod"`. |
| POST | `/api/payments/webhook` | HMAC sig | Razorpay async webhook receiver (CSRF-exempt). Verifies `X-Razorpay-Signature` with `RAZORPAY_WEBHOOK_SECRET`. |

### Frontend flow (Checkout.jsx)

1. On mount, GET `/api/payments/config` → know whether real Razorpay is enabled.
2. On *Pay*, POST `/api/orders` with cart items + method.
3. If `payCfg.enabled` and method ≠ COD: lazy-load `https://checkout.razorpay.com/v1/checkout.js`, open `new Razorpay({ key, amount, order_id, handler })`. On `handler` success, POST `/api/orders/{oid}/verify` with the three Razorpay fields.
4. Otherwise (COD, or no keys configured): POST `/api/orders/{oid}/pay` (mock).

### Test cards / UPI

Razorpay test mode accepts:
- **Card**: `4111 1111 1111 1111` · any future expiry · any CVV · OTP `1234`
- **UPI**: `success@razorpay` (success) · `failure@razorpay` (failure)
- **Netbanking**: choose any bank, then click *Success* / *Failure* on the simulator
See <https://razorpay.com/docs/payments/payments/test-card-upi-details/>.

### Webhook (optional)

In the Razorpay Dashboard add a webhook pointing to
`https://<your-domain>/api/payments/webhook` with events `payment.captured`,
`payment.authorized`, `payment.failed`. Paste the generated secret into
`RAZORPAY_WEBHOOK_SECRET`. The receiver verifies HMAC-SHA256 of the raw body
and updates the matching order's `payment_status` / `status`.

### Security

- Secrets loaded only from `backend/.env`; **never** sent to the client
- Backend-mediated order creation (no client-controlled amount)
- HMAC-SHA256 signature verification on every payment success + webhook
- COD never touches the gateway (no signature, no Razorpay order)
- `compare_digest` used for constant-time comparison on webhook signatures

## Auth

- JWT in `httpOnly` cookie `kb_token`
- Double-submit CSRF via `csrf_token` cookie + `X-CSRF-Token` header (enforced on all mutations)
- Brute-force lockout: 5 failed logins → 15-minute lockout per `{ip}:{email}`
- Password reset: single-use 1-hour token logged to backend stderr (swap for SendGrid/Resend in prod)
- Optional Emergent Google OAuth at `/api/auth/google/session`

## Testing

```bash
# Backend
cd /app && python -m pytest backend/tests/ -q
# (75 tests; credentials & target URL loaded from backend/tests/.env.test)
```

Frontend E2E is exercised via `testing_agent_v3` — see `/app/test_reports/`.

## Environment variables reference

See `backend/.env.example` for the full list. Frontend reads only
`REACT_APP_BACKEND_URL` from `frontend/.env`.

## License

Proprietary — KisanBaazar internal.
