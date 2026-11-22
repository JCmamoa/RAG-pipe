"""Endpoints internos (chamados pelo MinIO). Não exponha na internet: restrinja na borda (proxy/rede)."""
import hmac
import logging
from urllib.parse import unquote_plus

from fastapi import APIRouter, HTTPException, Request

from .. import storage
from ..config import settings
from ..db import org_session
from ..ingestion import enqueue_if_pending

router = APIRouter(prefix="/internal", include_in_schema=False)
log = logging.getLogger(__name__)


def _authorized(header: str | None) -> bool:
    if not header:
        return False
    token = header.removeprefix("Bearer ").strip()
    return hmac.compare_digest(token.encode(), settings.minio_webhook_token.encode())


@router.post("/minio-events")
async def minio_events(request: Request):
    if not _authorized(request.headers.get("authorization")):
        raise HTTPException(401, "não autorizado")
    payload = await request.json()
    enqueued = 0
    for record in payload.get("Records", []):
        if not str(record.get("eventName", "")).startswith("s3:ObjectCreated"):
            continue
        s3 = record.get("s3", {})
        if s3.get("bucket", {}).get("name") != settings.minio_bucket:
            continue
        key = unquote_plus(s3.get("object", {}).get("key", ""))
        parsed = storage.parse_object_key(key)
        if parsed is None:
            log.warning("evento com chave fora do padrão; ignorado", extra={"object_key": key})
            continue
        org_id, doc_id = parsed
        # O org_id da chave define o tenant; com RLS, um doc de OUTRA org simplesmente não é achado.
        async with org_session(org_id) as session:
            if await enqueue_if_pending(session, doc_id, org_id):
                enqueued += 1
    return {"enqueued": enqueued}
