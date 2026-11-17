# StudBud

Search your own academic PDFs and get an explanation grounded in the source, with a
one-click jump to the exact page.

- **Frontend:** Next.js 16 (App Router, React 19), deployed on Vercel
- **Backend:** Python 3.13 + FastAPI, in-process ingestion worker, Render free + Cloudflare keepalive
- **Database:** PostgreSQL 16 + pgvector (hybrid vector + full-text search)
- **Storage:** local filesystem in development, Cloudflare R2 in production
- **AI:** Groq chat completions and optional Llama 4 vision captions for figures, plus
  local FastEmbed embeddings (`nomic-ai/nomic-embed-text-v1.5-Q`, 768-d) so semantic
  search does not depend on Groq's embeddings endpoint. Deterministic hash embeddings are
  the last-resort offline fallback.
- **RAG:** page- and section-aligned chunks with overlap; page previews and extracted
  figures stored beside each citation; optional Tesseract OCR for scanned pages

Product context lives in [PRODUCT.md](PRODUCT.md); the full implementation plan is in
[implementations.md](implementations.md).

## Local setup

Requirements: Docker, Python 3.13, `uv`, Node 20+, npm.

```bash
# 1. Start PostgreSQL with pgvector
docker compose up -d db

# 2. Backend
cd backend
cp .env.example .env          # then edit KEY_PEPPER and ADMIN_API_SECRET
uv sync
uv run alembic upgrade head
uv run uvicorn studbud_backend.main:app --reload --port 8000

# 3. Frontend (second terminal)
cd frontend/web
cp .env.example .env.local    # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                   # http://localhost:3000
```

Schema changes go through Alembic (`backend/migrations/`). `AUTO_CREATE_TABLES=false` is
the default; the Docker entrypoint runs `alembic upgrade head` before starting the API.
For a fresh local database, just run the migration command above. Tests use a separate
`studbud_test` database and create its schema directly.

### Database migrations

```bash
cd backend
uv run alembic upgrade head           # apply
uv run alembic revision --autogenerate -m "describe change"
uv run alembic check                  # model/schema drift check
```

Generate migrations against a database that is already at the current revision. Run the
upgrade on a fresh database before committing to prove the migration works from zero.

### Create the first user and access key

Admin endpoints require `X-Admin-Secret` equal to `ADMIN_API_SECRET`.
They are disabled (404) when that environment variable is unset.

```bash
# Create a user
curl -X POST http://localhost:8000/api/admin/users \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: dev-admin-secret-change-me" \
  -d '{"display_name":"Demo Learner"}'

# Issue a key for that user (default expiry: 30 days)
curl -X POST http://localhost:8000/api/admin/users/<USER_ID>/keys \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: dev-admin-secret-change-me" \
  -d '{}'
```

The plaintext key is returned **once**. Store it nowhere else; the database keeps only
an HMAC-SHA-256 hash. Sign in at `/sign-in` with the key.

Other admin routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/admin/users` | List users and key metadata |
| PATCH | `/api/admin/users/{id}` | Disable or re-enable a user |
| POST | `/api/admin/keys/{keyId}/revoke` | Revoke a key and its sessions |

### Groq

**Embeddings do not use Groq.** Groq's hosted embeddings endpoint is not available on
many accounts (404). StudBud defaults to local FastEmbed with the quantized Nomic model.
In the Docker image the model is pre-downloaded into `/app/.fastembed`.

`GROQ_API_KEY` enables:

- Groq chat completions for the explanation page
- optional figure/diagram captions through a vision-capable model

Groq rotates its model catalog. As of this setup, `openai/gpt-oss-120b` is available for
chat and there is no working Groq vision model on this account. For figure captions, add
a free Gemini API key:

```text
GEMINI_API_KEY=...
GEMINI_VISION_MODEL=gemini-3.5-flash-lite
VISION_PROVIDER=auto
```

`auto` uses Gemini only. Set `VISION_PROVIDER=groq` explicitly if your Groq account has a
working vision model, or `none` to disable captions. If captioning fails, ingestion
continues and the figure is stored without a caption.

Embedding providers:

```text
EMBEDDING_PROVIDER=auto        # local FastEmbed, hash fallback if it fails
EMBEDDING_PROVIDER=fastembed   # local semantic model only
EMBEDDING_PROVIDER=groq        # hosted; may return 404
EMBEDDING_PROVIDER=hash        # offline bag-of-words fallback
LOCAL_EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5-Q
```

The first local embedding run downloads the model (about 130 MB) unless the Docker cache
is pre-baked. Existing documents indexed with a different embedding model keep their old
vectors and will not participate in vector search until re-indexed. Queue them again:

```bash
cd backend
uv run python scripts/reindex_documents.py --all
```

The worker replaces chunks, page previews, and figures. Run this after changing the
embedding model, chunk settings, OCR, or vision captioning.

Verify chat, embeddings, and vision before indexing a real library:

```bash
cd backend
uv run python scripts/smoke_groq.py
```

## Testing

```bash
# Backend: needs the docker compose database
cd backend
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts

# Frontend
cd frontend/web
npm run lint
npm test
npm run build

# Full UI flow screenshots + theme persistence check
# (creates a review user + uploads the sample PDF)
node scripts/screenshots.mjs
```

GitHub Actions runs backend tests, Next lint/unit/build, and the full browser flow against
a pgvector Postgres service. See `.github/workflows/ci.yml`.

## Retrieval evaluation

`backend/evaluation/sample_questions.json` shows the dataset shape. Replace it with 30–50
questions from your real books before tuning chunks or reranking. Each answerable question
needs a document and expected page or page range.

```bash
cd backend
STUDBUD_KEY=sb_... uv run python scripts/evaluate_retrieval.py \
  --dataset evaluation/sample_questions.json --k 10 --min-recall 0.8
```

It reports Recall@K, MRR, and top-1 page accuracy. Add questions whose answers are absent
from the library with `"answerable": false`; those are scored by the explanation
no-answer check, not by retrieval metrics. Do not tune `CHUNK_TARGET_TOKENS`,
`CHUNK_OVERLAP_TOKENS`, or reranking without this set.

## Quotas and maintenance

Per-user limits are enforced server-side:

```text
USER_MAX_DOCUMENTS=50
USER_MAX_PAGES=5000
USER_MAX_STORAGE_MB=1024
USER_DAILY_UPLOADS=20
USER_DAILY_EXPLANATIONS=100
```

The IP rate limits are separate. Adjust both for the tier you can afford.

Delete a document through the API removes its original file and its asset prefix. To find
storage objects left behind by crashes or interrupted deletes:

```bash
cd backend
uv run python scripts/cleanup_orphans.py           # dry run
uv run python scripts/cleanup_orphans.py --apply   # delete
```

On R2, also enable lifecycle rules for abandoned multipart uploads and keep versioning
off unless you can pay for retained versions. Page previews increase storage use; lower
`PAGE_PREVIEW_DPI` or reduce `MAX_PAGES` if the free bucket gets tight.

## Monitoring

- `GET /healthz` checks the database and returns 503 when unavailable.
- Every response carries `X-Request-ID`; API logs include the request ID, method, path,
  status, and duration.
- Set `SENTRY_DSN` on Render to enable backend error reporting. PII and request bodies are
  disabled, so document content is not sent.
- Vercel keeps frontend build/runtime logs for the Next app.
- Add an external uptime check against `/healthz` and a second against the Vercel sign-in
  page.

## Free-tier deployment

### 1. Neon PostgreSQL

- Create a free Neon project and copy the pooled `postgresql://` connection string.
- Convert it to a SQLAlchemy async URL:

```text
postgresql+asyncpg://USER:PASSWORD@HOST/DBNAME?ssl=require
```

- The initial Alembic migration runs `CREATE EXTENSION IF NOT EXISTS vector` before
  creating tables.

### 2. Cloudflare R2

- Create a private bucket and an API token with object read/write permissions.
- Set `STORAGE_BACKEND=r2`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`.

### 3. Render (backend, free + keepalive)

Render free: 512 MB RAM, sleeps after 15 minutes idle, 750 instance hours/month. Gemini
embeddings run remotely, so the local FastEmbed model is not loaded. One always-on service
fits inside 750 hours; a Cloudflare Worker cron keeps it warm.

- Use `render.yaml`, or create a Docker web service with root `backend`.
- Health check: `/healthz`.
- The Docker entrypoint runs `alembic upgrade head`; keep `AUTO_CREATE_TABLES=false` and
  `AUTO_MIGRATE=true`.
- Copy the service URL; set it as `HEALTH_URL` in
  `infrastructure/cloudflare/keepalive/wrangler.toml`.
- Deploy the keepalive Worker:

```bash
cd infrastructure/cloudflare/keepalive
npx wrangler login
npx wrangler deploy
```

Without the ping, the first request after 15 idle minutes pays a ~60-second cold start.
With the 5-minute ping, the service stays warm. Render free hours cover 24/7 for one
service; monitor usage in the Render dashboard.

Required environment variables:

```text
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://...
KEY_PEPPER=<long random string>
ADMIN_API_SECRET=<long random string>
GROQ_API_KEY=...
GROQ_CHAT_MODEL=openai/gpt-oss-120b
VISION_PROVIDER=auto
GEMINI_API_KEY=...
GEMINI_VISION_MODEL=gemini-3.5-flash
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_MODEL=nomic-embed-text-v1_5
EMBEDDING_PROVIDER=gemini
CHUNK_TARGET_TOKENS=650
CHUNK_OVERLAP_TOKENS=100
FIGURE_CAPTIONING_ENABLED=true
OCR_ENABLED=true
OCR_LANGUAGE=eng
OCR_DPI=200
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
USER_MAX_DOCUMENTS=50
USER_MAX_PAGES=5000
USER_MAX_STORAGE_MB=1024
USER_DAILY_UPLOADS=20
USER_DAILY_EXPLANATIONS=100
```

`COOKIE_SAMESITE=none` requires `COOKIE_SECURE=true` and HTTPS. When frontend and API
share a registrable domain, switch to `lax`. Allowed CORS origins come from
`FRONTEND_ORIGINS` (comma-separated).

If Render wakes after a missed ping, the worker requeues ingestion jobs whose leases
expired, so processing resumes without duplicate chunks.

### 4. Vercel (Next.js)

- Import the repository, set the project root to `frontend/web`.
- Framework preset: Next.js. Build command: `npm run build`.
- Add `NEXT_PUBLIC_API_BASE_URL=https://<render-service>.onrender.com` to the Vercel
  environment variables for Production (and Preview if needed), then redeploy.
- Add the Vercel production origin to `FRONTEND_ORIGINS` on Render, for example:
  `https://studbud.vercel.app`.
- The app uses client-side API calls, so no server-side database secrets belong on Vercel.

### Alternative backend hosts

- **Hugging Face Docker Space**: requires PRO (free Docker Spaces were removed). Not used.
- **Oracle Cloud Always Free VM**: 24 GB ARM always-on VM, no cold start. More ops work.
- **Google Cloud e2-micro**: always-free VM, 1 GB RAM, needs a GCP billing account.
- **Modal / Cloud Run**: require billing account and worker redesign. Not used here.

## Current limitations

- OCR uses Tesseract when the binary is available (`OCR_ENABLED=true`). The Docker image
  installs it. If it is missing or fails, scanned pages are reported as Needs OCR instead
  of pretending they were indexed. OCR pages do not retain font-size heading detection.
- Figures are always extracted and shown with their source page. Automatic captions
  require a Gemini key (`GEMINI_API_KEY`); without one, figures are stored without captions.
- Page previews are rendered for every page, which increases ingestion storage and cost.
- Flat library: no collections, sharing, or public links.
- Access keys are issued by an administrator; there is no self-registration or password
  reset.
- Explanations are generated on request and cached per explanation record; refreshing
  without `?explanationId=` regenerates.
- Local FastEmbed is the local-development default. Render uses hosted Gemini embeddings
  to stay under 512 MB. The hash fallback is not semantic.
- Re-index documents after changing the embedding provider or model; old vectors are
  intentionally excluded from search.
- In-process rate limits assume one API process, which matches the single Render service.
