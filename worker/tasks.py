import logging
import os
import time

import httpx
import psycopg
import urllib3
from minio.error import ServerError

from celery_app import celery_app
from chunking import chunk_pages
from config import settings
from db import org_tx, plain_tx
from embeddings import EmbeddingConfigError, embed_all, vector_literal
from extract import ExtractionError, extract_pages
from storage import delete_object, download_to_temp

log = logging.getLogger(__name__)

# Falhas transitórias: vale tentar de novo com backoff.
RETRYABLE = (httpx.HTTPError, urllib3.exceptions.HTTPError, ServerError, psycopg.OperationalError,
             ConnectionError, TimeoutError, OSError)


def _fail(org_id: str, document_id: str, message: str) -> None:
    with org_tx(org_id) as conn:
        conn.execute("UPDATE documents SET status='failed', error=%s, updated_at=now() WHERE id=%s",
                     (message[:500], document_id))
    log.error("ingestão falhou", extra={"document_id": document_id, "org_id": org_id, "reason": message})


@celery_app.task(name="ping")
def ping() -> str:
    return "pong"


@celery_app.task(bind=True, name="ingest_document", max_retries=3)
def ingest_document(self, document_id: str, org_id: str) -> str:
    """PDF no MinIO -> texto -> chunks -> embeddings -> pgvector. Idempotente."""
    started = time.perf_counter()
    ctx = {"document_id": document_id, "org_id": org_id, "attempt": self.request.retries + 1}

    # 1) Reivindica o documento. FOR UPDATE serializa execuções concorrentes do mesmo job.
    with org_tx(org_id) as conn:
        row = conn.execute("SELECT status, object_key FROM documents WHERE id=%s AND org_id=%s FOR UPDATE",
                           (document_id, org_id)).fetchone()
        if row is None:
            log.warning("documento inexistente (apagado?)", extra=ctx)
            return "missing"
        status, object_key = row
        if status == "ready":
            log.info("já processado; ignorando entrega duplicada", extra=ctx)
            return "already_ready"
        if status not in ("queued", "processing"):
            log.warning("status inesperado %s; ignorando", status, extra=ctx)
            return "skipped"
        conn.execute("UPDATE documents SET status='processing', error=NULL, updated_at=now() WHERE id=%s",
                     (document_id,))

    path = None
    try:
        # 2) Trabalho pesado fora de qualquer transação (nada de conexão presa durante OCR/embeddings).
        path = download_to_temp(object_key)
        pages = extract_pages(path)
        chunks = chunk_pages(pages, settings.chunk_size_chars, settings.chunk_overlap_chars,
                             settings.chunk_min_chars)
        if not chunks:
            raise ExtractionError("Nenhum texto extraível (PDF vazio ou OCR sem resultado)")
        vectors = embed_all([c.content for c in chunks])

        # 3) Troca atômica: apaga os chunks antigos e grava os novos na MESMA transação.
        rows = [(org_id, document_id, c.index, c.page, c.content, vector_literal(v), settings.embedding_model)
                for c, v in zip(chunks, vectors)]
        with org_tx(org_id) as conn:
            conn.execute("DELETE FROM chunks WHERE document_id=%s", (document_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (org_id, document_id, chunk_index, page, content, embedding, "
                    "embedding_model) VALUES (%s, %s, %s, %s, %s, %s::vector, %s)", rows)
            conn.execute("UPDATE documents SET status='ready', error=NULL, page_count=%s, updated_at=now() "
                         "WHERE id=%s", (len(pages), document_id))
        log.info("documento indexado", extra={**ctx, "pages": len(pages), "chunks": len(chunks),
                                              "seconds": round(time.perf_counter() - started, 2)})
        return "ready"

    except (ExtractionError, EmbeddingConfigError) as exc:  # permanente
        _fail(org_id, document_id, str(exc))
        return "failed"
    except RETRYABLE as exc:
        if self.request.retries < self.max_retries:
            log.warning("falha transitória; nova tentativa", extra={**ctx, "error": repr(exc)})
            raise self.retry(exc=exc, countdown=min(15 * 2 ** self.request.retries, 300))
        _fail(org_id, document_id, f"Falha após {self.max_retries + 1} tentativas: {exc}")
        return "failed"
    except Exception as exc:
        log.exception("erro inesperado", extra=ctx)
        _fail(org_id, document_id, f"Erro interno: {type(exc).__name__}")
        return "failed"
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


@celery_app.task(name="reap_stuck_documents")
def reap_stuck_documents() -> dict:
    """Limpeza horária (beat). Percorre as orgs porque o RLS impede ver todas de uma vez.

    - queued/processing há mais de 30 min  -> failed (o usuário pode usar /reindex)
    - pending há mais de 1 dia             -> remove registro e objeto órfão
    """
    with plain_tx() as conn:
        org_ids = [r[0] for r in conn.execute("SELECT id FROM organizations").fetchall()]
    stuck = removed = 0
    for org_id in org_ids:
        with org_tx(org_id) as conn:
            stuck += conn.execute(
                "UPDATE documents SET status='failed', error='Tempo limite excedido no processamento', "
                "updated_at=now() WHERE status IN ('queued','processing') "
                "AND updated_at < now() - interval '30 minutes'").rowcount
            old = conn.execute("DELETE FROM documents WHERE status='pending' "
                               "AND created_at < now() - interval '1 day' RETURNING object_key").fetchall()
        for (key,) in old:
            removed += 1
            try:
                delete_object(key)
            except Exception:
                log.warning("objeto órfão não removido", extra={"object_key": key})
    log.info("reaper concluído", extra={"stuck_failed": stuck, "pending_removed": removed})
    return {"stuck_failed": stuck, "pending_removed": removed}
