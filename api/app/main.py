import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import metrics
from .config import settings
from .db import engine
from .logging_conf import configure_logging, request_id_var
from .rate_limit import get_redis
from .routers import auth, chat, documents, internal, search, users

configure_logging(settings.log_level)
log = logging.getLogger("app.access")

app = FastAPI(title="RAG Platform API")
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(internal.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

_QUIET = {"/health", "/ready", "/metrics"}


@app.middleware("http")
async def observability(request: Request, call_next):
    """Request-id (entrada/saída), métricas Prometheus e log de acesso JSON."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        path = route.path if route else "unmatched"  # template da rota: evita explosão de cardinalidade
        metrics.HTTP_REQUESTS.labels(request.method, path, str(status_code)).inc()
        metrics.HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        if request.url.path not in _QUIET:
            log.info("request", extra={
                "method": request.method, "path": request.url.path, "status": status_code,
                "ms": int(elapsed * 1000), "user_id": getattr(request.state, "user_id", None),
                "org_id": getattr(request.state, "org_id", None)})
        request_id_var.reset(token)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/ui/")


@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["infra"])
async def ready():
    """Readiness: dependências críticas respondem?"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await get_redis().ping()
    except Exception:
        log.exception("readiness falhou")
        raise HTTPException(503, "dependência indisponível")
    return {"status": "ready"}


@app.get("/metrics", tags=["infra"], include_in_schema=False)
async def prometheus_metrics():
    body, content_type = metrics.render()  # produção: restrinja por rede/proxy
    return Response(body, media_type=content_type)
