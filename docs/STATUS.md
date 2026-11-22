# Project status

Roadmap: 1 infrastructure ✅ · 2 auth and organizations ✅ · 3 upload + event + task ✅ ·
4 extraction, chunking, embeddings ✅ · 5 vector search + isolation tests ✅ · 6 WebSocket chat ✅ ·
7 RLS, rate limiting, observability ✅ · documentation (English) ✅

## What has and has not been verified

The code was written and reviewed in an environment **without Docker or network access**.

| Verified | How |
|---|---|
| Every Python file compiles; no unused imports | `compileall` + an AST check |
| `docker-compose.yml` is valid YAML; `01-app-role.sh` is valid shell with LF endings | PyYAML, `sh -n` |
| Chunking logic (6 tests) | Run locally (pure Python module) |
| Code review pass | Fixed: stale ORM state after atomic `UPDATE` (documents stayed `pending` in responses); transient MinIO network errors were treated as permanent failures; WebSocket tests seeded data on a foreign event loop |

**Never executed:** `docker compose up`, Alembic migrations, the API test suite, the worker, MinIO events,
Ollama, `scripts/smoke.ps1`, and the GitHub Actions workflow. Expect small fixes on first boot.

### Most likely places to need fixes

- [ ] `storage.presign_upload`: the `minio` SDK `PostPolicy` API (method names, returned fields).
- [ ] MinIO webhook: `MINIO_NOTIFY_WEBHOOK_*` variables and the `Authorization` header format
      (the handler accepts the token with or without `Bearer `). Fallback: `POST /documents/{id}/confirm`.
- [ ] asyncpg codec for the `vector` type (`api/app/db.py`) and `CAST(:q AS vector)` in `retrieval.py`.
- [ ] SQLAlchemy `after_begin` hook applying `app.org_id` — run `tests/test_rls.py` first.
- [ ] `hnsw.iterative_scan` needs pgvector ≥ 0.8 (the `pgvector/pgvector:pg17` image should ship it).
- [ ] Ollama `/v1/embeddings` with `bge-m3` (1024 dimensions).
- [ ] Hot reload on Docker Desktop for Windows (`WATCHFILES_FORCE_POLLING=true` if needed).
- [ ] `.github/workflows/ci.yml`.

### Suggested validation order

1. `docker compose down -v && docker compose up --build` (no LLM) and watch API, MinIO and the worker start.
2. `docker compose exec api pytest tests/test_auth_isolation.py tests/test_rls.py -v`
3. `docker compose exec api pytest -v` and `docker compose exec worker pytest -v`
4. `docker compose --profile local-llm up`, then `scripts/smoke.ps1` and the UI at `/ui/`.

## Remaining work

**Answer quality**
- [ ] Minimum-similarity threshold (currently always returns the top-k) and reranking.
- [ ] Hybrid search (tsvector/BM25 + vectors) with reciprocal rank fusion.
- [ ] Query rewriting with chat history ("and the second one?").
- [ ] Offline RAG evaluation (question/answer set, recall@k).

**Product**
- [ ] Persist conversations (`conversations`/`messages`, also under RLS).
- [ ] Cancel an in-flight generation (the WebSocket loop is currently sequential).
- [ ] Per-document filtering in the UI; pagination for `GET /documents`.
- [ ] Per-organization quotas (documents, pages, questions per day).

**Security and operations**
- [ ] Refresh tokens and logout with revocation; email verification; invitations instead of open sign-up.
- [ ] RLS on `users`/`organizations` (needs a rethink of login, which looks users up by global email).
- [ ] Keep `/metrics` and `/internal/*` off the public internet; TLS; secrets manager.
- [ ] Antivirus scan (ClamAV) before indexing; per-document page/time limits.
- [ ] Run beat as its own service; dead-letter handling and alerts; Prometheus + Grafana in compose.
- [ ] Changing the embedding model: new migration (dimension) + batch reindex.
- [ ] Index scale: partition `chunks` by organization if one large tenant dominates the HNSW index.
- [ ] Translate remaining Portuguese code comments, API error messages and the RAG system prompt to English
      (documentation is already in English).
