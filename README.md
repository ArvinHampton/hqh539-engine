# HQH-539-512

**Hampton Qutrit Hash (HQH)** — **539 steps (18 + 521)**, wrapped in **SHA3-512**.

High-volume hash engine and pay-to-encrypt service for 539 Labs LLC.

| | |
|--|--|
| **Live app** | [https://www.539labs.org](https://www.539labs.org) *(after DNS)* · [onrender fallback](https://hqh-539-512-encryption-generator-for.onrender.com) |
| **File API** | [https://hqh539-webhook.onrender.com/file/health](https://hqh539-webhook.onrender.com/file/health) |
| **Repo** | [GitHub](https://github.com/ArvinHampton/HQH-539-512-Encryption-Generator-for-High-Volume-Data-PPV-) |

---

## Pipeline

```
message || salt
    → SHA3-512 (seed)
    → 539 T3 qutrit steps  (18 prefix + 521 suffix)
    → SHA3-512 (finalize)
    → 128 hex chars (512-bit digest)
```

## Features

- **Hash Computation** — HQH-539-512 digests
- **File encrypt / decrypt** — HQH KDF + ChaCha20-Poly1305 (full-page portal, not Streamlit upload)
- **Avalanche demo** & **539-step visualization**
- **Stripe** credit packs + Pro subscription
- **Master operator** account overrides (`MASTER_EMAILS`)

## Architecture

| Component | Runtime | Role |
|-----------|---------|------|
| `Dockerfile` → **HQH-539-512** | Streamlit | UI, auth, billing checkout |
| `Dockerfile.webhook` → **HQH-539-512-webhook** | Flask/gunicorn | Stripe webhooks + `/file/*` encrypt portal |
| Postgres | Render free DB | Shared users + credit ledger |

Encrypt/decrypt **never** uses the Streamlit websocket (avoids Render 502 session drops).  
Logged-in users open a signed **File Portal** link that POSTs multipart data to the webhook service.

## Quick start (local)

```bash
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill Stripe + optional DATABASE_URL
streamlit run app.py
```

Webhook + file API:

```bash
# requires same DATABASE_URL / secrets as the app
gunicorn -b 0.0.0.0:5001 webhook_handler:app
```

Docker:

```bash
docker build -t hqh539-512 .
docker run -p 8080:8080 --env-file .env hqh539-512
```

## Environment variables

See [`.env.example`](.env.example). Important production keys:

| Variable | Used by | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | app + webhook | Shared Postgres |
| `STRIPE_SECRET_KEY` | both | Stripe API + file-token HMAC |
| `STRIPE_WEBHOOK_SECRET` | webhook | Stripe signature verify |
| `STRIPE_PRICE_ID_*` | app | Checkout prices |
| `APP_URL` | app | Public site URL (Stripe return) |
| `FILE_SERVICE_URL` | app | Base URL of webhook/file service |
| `MASTER_EMAILS` | both | Operator overrides (comma-separated) |
| `HQH539_MAX_DEPOSIT_MB` | both | Upload cap (default `2048`) |
| `HQH539_BYTES_PER_CREDIT` | both | Toll: bytes per credit (default `65536`) |

## Custom domain (www.539labs.org)

DNS is managed at **GoDaddy** (`domaincontrol.com`).

| Type | Name | Value |
|------|------|--------|
| **CNAME** | `www` | `hqh-539-512-encryption-generator-for.onrender.com` |
| **A** | `@` | `216.24.57.1` |

1. Remove the old **A** record pointing at `160.153.0.74`.
2. Remove any **AAAA** records for `@` / `www`.
3. In [Render → HQH-539-512 → Custom Domains](https://dashboard.render.com/web/srv-d99rig8k1i2s73elq0rg), click **Verify**.
4. Apex `539labs.org` redirects to `www.539labs.org` once verified.

## Deploy

Pushes to `main` auto-deploy on Render (Docker).

```bash
git push origin main
```

Manual redeploy: Render dashboard → service → Manual Deploy.

## Project layout

```
app.py              # Streamlit UI
hqh539.py           # HQH-539-512 primitive
crypto_hqh.py       # File encrypt package format
encrypt_ui.py       # Portal launcher (signed links)
file_service.py     # Flask /file/portal, /file/encrypt, /file/decrypt
file_tokens.py      # HMAC session tokens for file portal
webhook_handler.py  # Stripe + file routes
database.py         # Users, credits, ledger
billing.py          # Stripe Checkout
Dockerfile          # Streamlit web service
Dockerfile.webhook  # Flask file + webhook service
render.yaml         # Blueprint sketch
```

## License

Apache-2.0 — see [LICENSE](LICENSE).

---

© 539 Labs LLC · HQH-539-512
