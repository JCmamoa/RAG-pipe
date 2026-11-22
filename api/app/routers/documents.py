import asyncio
import logging
import re
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..config import settings
from ..deps import get_current_user, get_org_session
from ..ingestion import enqueue_if_pending
from ..models import Document, User
from ..rate_limit import limit_by_user
from ..schemas import DocumentOut, UploadFormOut, UploadRequestIn, UploadTicketOut

router = APIRouter(prefix="/documents", tags=["documents"])
log = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name
    return re.sub(r"[\x00-\x1f\x7f]", "", base).strip()[:255]


async def _get_doc(session: AsyncSession, user: User, doc_id: uuid.UUID) -> Document:
    # 404 (e não 403) para documento de outra org: não revela a existência do id.
    doc = await session.scalar(select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
                               .execution_options(populate_existing=True))  # relê o estado atual do banco
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado")
    return doc


@router.post("", response_model=UploadTicketOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(limit_by_user("upload", "rl_upload_per_min"))])
async def request_upload(body: UploadRequestIn, user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_org_session)):
    """Passo 1 do upload: cria o registro (pending) e devolve um POST pré-assinado para o MinIO.

    O cliente envia o PDF direto ao MinIO (a API nunca toca nos bytes). Quando o objeto chega,
    o MinIO avisa /internal/minio-events e a ingestão é enfileirada.
    """
    filename = _safe_filename(body.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Envie um arquivo .pdf")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if body.size_bytes > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Máximo de {settings.max_upload_mb} MB")

    doc_id = uuid.uuid4()
    doc = Document(id=doc_id, org_id=user.org_id, uploaded_by=user.id, filename=filename,
                   object_key=storage.build_object_key(user.org_id, doc_id),
                   content_type="application/pdf", size_bytes=body.size_bytes, status="pending")
    session.add(doc)
    await session.commit()
    form = storage.presign_upload(doc.object_key, max_bytes)
    return UploadTicketOut(document=DocumentOut.model_validate(doc), upload=UploadFormOut(**form))


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_org_session)):
    rows = await session.scalars(
        select(Document).where(Document.org_id == user.org_id).order_by(Document.created_at.desc()))
    return list(rows)


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_org_session)):
    return await _get_doc(session, user, doc_id)


@router.post("/{doc_id}/confirm", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def confirm_upload(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_org_session)):
    """Plano B para o webhook (ex.: ambiente sem notificações do MinIO). Idempotente."""
    doc = await _get_doc(session, user, doc_id)
    if doc.status == "pending":
        if not await storage.object_exists(doc.object_key):
            raise HTTPException(status.HTTP_409_CONFLICT, "Upload ainda não concluído")
        await enqueue_if_pending(session, doc.id, user.org_id)
    return await _get_doc(session, user, doc_id)


@router.post("/{doc_id}/reindex", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def reindex(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                  session: AsyncSession = Depends(get_org_session)):
    """Reprocessa (ex.: após trocar o modelo de embedding). Só admin."""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permissão insuficiente")
    doc = await _get_doc(session, user, doc_id)
    if doc.status not in ("ready", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Documento está '{doc.status}'")
    await enqueue_if_pending(session, doc.id, user.org_id, from_status=(doc.status,), revert_to=doc.status)
    return await _get_doc(session, user, doc_id)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_org_session)):
    doc = await _get_doc(session, user, doc_id)
    if user.role != "admin" and doc.uploaded_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o autor ou um admin podem apagar")
    key = doc.object_key
    await session.execute(delete(Document).where(Document.id == doc.id, Document.org_id == user.org_id))
    await session.commit()  # chunks saem junto (ON DELETE CASCADE)
    try:
        await asyncio.to_thread(storage.delete_object, key)
    except Exception:
        log.warning("objeto não removido do storage", exc_info=True, extra={"object_key": key})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
