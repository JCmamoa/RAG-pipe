# RAG Platform

Asynchronous document ingestion and retrieval-augmented chat, with strict per-organization isolation.

Users upload large PDFs straight to object storage. A storage event triggers a Python worker that extracts text
(with OCR fallback), chunks it, generates embeddings and stores them in PostgreSQL with `pgvector`. A chat
interface streams answers over WebSockets while the model retrieves from the indexed documents — and **only**
from the documents of the logged-in user's organization.

> **Status:** the code was written and statically checked, but the full stack has not been run end to end yet.
> See [`docs/STATUS.md`](docs/STATUS.md) for what is verified, what is not, and the remaining work.

## Features

- **Non-blocking uploads:** presigned POST straight to MinIO (S3-compatible); the API never handles file bytes.
  The signed policy enforces object key, content type and maximum size server-side.
- **Event-driven ingestion:** MinIO webhook → API → Celery task. Idempotent state machine
  (`pending → queued → processing → ready | failed`), retries with backoff, periodic reaper for stuck jobs.
- **Ingestion pipeline:** PyMuPDF text extraction, Tesseract OCR for scanned pages, page-aware chunking with
  overlap, batched embeddings, atomic delete-and-insert of chunks.
- **Vector search:** pgvector HNSW (cosine) with iterative scan so filtered queries still return `k` results.
- **Streaming chat with citations:** WebSocket protocol with per-question token revalidation, history, and
  source references (file and page).
- **Multi-tenant security (3 layers):** JWT claims checked against the database, `org_id` filters in every
  query, and PostgreSQL Row-Level Security (`FORCE`d, fail-closed, non-superuser runtime role).
- **Operations:** structured JSON logs with request IDs, Prometheus metrics, Flower, readiness probe,
  Redis-backed rate limiting.
- **Provider-agnostic AI:** any OpenAI-compatible API for embeddings and chat (Ollama by default).

## Quick start

Requires Docker (Docker Desktop with WSL2 on Windows).

**PowerShell**

```powershell
Copy-Item .env.example .env

# Generate random secrets
function New-Secret { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString('x2') }) -join '' }
(Get-Content .env) -replace '^JWT_SECRET=.*', "JWT_SECRET=$(New-Secret)" `
                   -replace '^MINIO_WEBHOOK_TOKEN=.*', "MINIO_WEBHOOK_TOKEN=$(New-Secret)" | Set-Content .env -Encoding ascii
```

**bash**

```bash
cp .env.example .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/; s/^MINIO_WEBHOOK_TOKEN=.*/MINIO_WEBHOOK_TOKEN=$(openssl rand -hex 32)/" .env
```

Then start the stack:

```bash
# With local LLM + embeddings (Ollama pulls the models on first run: several GB)
docker compose --profile local-llm up --build

# Without Ollama (set EMBEDDING_* and LLM_* in .env to use a hosted API)
docker compose up --build
```

If you ran an earlier version of this project, recreate the volumes first (`docker compose down -v`): the
restricted `rag_app` database role is only created when the Postgres volume is first initialized.

| Service | URL |
|---|---|
| Web UI (login, upload, chat) | http://localhost:8000/ui/ |
| API / Swagger | http://localhost:8000/docs |
| Prometheus metrics | http://localhost:8000/metrics |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |
| Flower (Celery) | http://localhost:5555 (admin / admin) |

## Testing

```bash
docker compose exec api pytest -v        # isolation, RLS, webhook, search, WebSocket, rate limit
docker compose exec worker pytest -v     # chunking
```

End-to-end smoke test with your own PDF (PowerShell 5.1+ on Windows 10; uses the bundled `curl.exe`):

```powershell
.\scripts\smoke.ps1 -Pdf .\my-document.pdf -Question "What is this document about?"
```

The security-critical tests are `api/tests/test_rls.py` (a query with **no** `WHERE` clause still cannot see
another organization's rows) and `api/tests/test_search_isolation.py` / `test_chat_ws.py` (retrieval and the
LLM prompt never contain another organization's content).

## API overview

| Endpoint | Purpose |
|---|---|
| `POST /auth/register` · `POST /auth/login` · `GET /auth/me` | Create organization + admin, log in, current user |
| `GET/POST/PATCH /users` | Admin-only user management within the organization |
| `POST /documents` | Create a `pending` document and get a presigned POST for MinIO |
| `GET /documents` · `GET /documents/{id}` | List / inspect documents and their status |
| `POST /documents/{id}/confirm` | Fallback when MinIO notifications are unavailable (idempotent) |
| `POST /documents/{id}/reindex` · `DELETE /documents/{id}` | Admin reindex; delete (admin or uploader) |
| `POST /search` | Semantic search over the caller's organization |
| `WS /ws/chat` | Streaming chat (protocol below) |
| `GET /health` · `GET /ready` · `GET /metrics` | Liveness, readiness, Prometheus |

### WebSocket protocol (`/ws/chat`)

```
client → {"type":"auth","token":"<jwt>"}                         first message; resend to renew the token
client → {"type":"question","text":"...","document_ids":[...]}    document_ids is optional
server → {"type":"ready"}  {"type":"sources","sources":[...]}  {"type":"token","text":"..."}
         {"type":"done"}   {"type":"error","code":"token_expired|rate_limited|upstream|...","message":"..."}
```

The token travels in the first message rather than the URL so it does not end up in proxy or access logs.

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example)). The embedding dimension must match the
`vector(1024)` column created by migration `0002`; changing models means a new migration plus a reindex.

## Repository layout

```
api/         FastAPI app: auth, users, documents, search, chat WebSocket, MinIO webhook, metrics
  app/         source code
  migrations/  Alembic (0001 base schema, 0002 documents/chunks/RLS)
  tests/       pytest suite (runs against the compose Postgres)
  web/         static demo UI served at /ui/
worker/      Celery worker: ingest_document task and hourly reaper (plus Flower)
db/init/     creates the non-superuser rag_app role so RLS actually applies
scripts/     smoke.ps1
docs/        ARCHITECTURE.md, STATUS.md
```

## Troubleshooting

- **`role "rag_app" does not exist`** — old Postgres volume; run `docker compose down -v`.
- **Port 5432 already in use** — a local Postgres is running; stop it or map `"5433:5432"` in the compose file.
- **Hot reload does not pick up changes on Windows** — add `WATCHFILES_FORCE_POLLING: "true"` to the `api` service.
- **`\r` errors in `db/init/01-app-role.sh`** — the file must use LF line endings (`.gitattributes` enforces this).
- **PowerShell blocks `smoke.ps1`** — `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
# Rag-platform
