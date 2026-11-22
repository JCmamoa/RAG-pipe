import asyncio
import logging
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .celery_client import celery_client
from .models import Document

log = logging.getLogger(__name__)


def enqueue_ingestion(document_id: uuid.UUID, org_id: uuid.UUID) -> None:
    celery_client.send_task("ingest_document", args=[str(document_id), str(org_id)])


async def enqueue_if_pending(session: AsyncSession, document_id: uuid.UUID, org_id: uuid.UUID,
                             from_status: tuple[str, ...] = ("pending",), revert_to: str = "pending") -> bool:
    """Transição atômica from_status -> queued, depois enfileira. Idempotente.

    Evento duplicado do MinIO ou duplo clique em /confirm: só o primeiro UPDATE acha a linha,
    então só um job é publicado. Se a publicação falhar, desfaz o status e propaga o erro
    (o webhook responde 500 e o MinIO reentrega).
    """
    result = await session.execute(
        update(Document)
        .where(Document.id == document_id, Document.org_id == org_id, Document.status.in_(from_status))
        .values(status="queued", error=None)
        .returning(Document.id))
    if result.scalar_one_or_none() is None:
        await session.rollback()
        return False
    await session.commit()
    try:
        await asyncio.to_thread(enqueue_ingestion, document_id, org_id)
    except Exception:
        log.exception("falha ao publicar tarefa; revertendo status", extra={"document_id": str(document_id)})
        await session.execute(update(Document)
                              .where(Document.id == document_id, Document.status == "queued")
                              .values(status=revert_to))
        await session.commit()
        raise
    log.info("ingestão enfileirada", extra={"document_id": str(document_id), "org_id": str(org_id)})
    return True
