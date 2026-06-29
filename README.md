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
# (53 tests; credentials & target URL loaded from backend/tests/.env.test)
```

Frontend E2E is exercised via `testing_agent_v3` — see `/app/test_reports/`.

## Environment variables reference

See `backend/.env.example` for the full list. Frontend reads only
`REACT_APP_BACKEND_URL` from `frontend/.env`.

## License

Proprietary — KisanBaazar internal.
