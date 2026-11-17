---
title: StudBud API
emoji: 📚
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
short_description: Grounded PDF search API for StudBud
---

# StudBud API Space

> Hugging Face now requires PRO for Docker Spaces. This package is optional; the selected
> free deployment is Render + Cloudflare keepalive.

Docker Space for the StudBud FastAPI backend. Upload this directory as the Space
repository; it contains the Dockerfile, Alembic migrations, and application code.

Required Space secrets/variables:

```text
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://...neon...
KEY_PEPPER=<long random string>
ADMIN_API_SECRET=<long random string>
GROQ_API_KEY=...
GROQ_CHAT_MODEL=openai/gpt-oss-120b
GEMINI_API_KEY=...
GEMINI_VISION_MODEL=gemini-3.5-flash
VISION_PROVIDER=auto
EMBEDDING_PROVIDER=gemini
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
STORAGE_BACKEND=r2
R2_ENDPOINT=...
R2_BUCKET=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
FRONTEND_ORIGINS=https://<your-vercel-domain>
COOKIE_SECURE=true
COOKIE_SAMESITE=none
AUTO_CREATE_TABLES=false
AUTO_MIGRATE=true
SENTRY_DSN=...
```

Notes:

- The Space filesystem is ephemeral. R2 is mandatory; never use local storage here.
- The Docker entrypoint runs `alembic upgrade head` before starting Uvicorn.
- The FastEmbed model and Tesseract OCR are baked into the image.
- Free Spaces pause after inactivity. Ping `/healthz` every 10–30 minutes with an
  external uptime monitor to keep the worker and API warm.
- The Space URL is public, but every user endpoint requires an access key and admin
  endpoints require `X-Admin-Secret`. Keep those secrets private.
- Add the Vercel origin to `FRONTEND_ORIGINS`; cross-site cookies require
  `COOKIE_SECURE=true` and `COOKIE_SAMESITE=none`.

Create/upload from the repository:

```bash
cd backend
uv run python scripts/prepare_hf_space.py
uv run hf auth login
uv run hf repos create <user>/studbud-api --type space --sdk docker --public
uv run hf upload <user>/studbud-api .hf-space . --repo-type space
```
