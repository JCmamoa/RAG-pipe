"""MinIO/S3. As funções de rede são síncronas: chame com asyncio.to_thread."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from minio import Minio
from minio.datatypes import PostPolicy
from minio.error import S3Error

from .config import settings

_creds = dict(access_key=settings.minio_root_user, secret_key=settings.minio_root_password,
              region=settings.minio_region)
# `region` fixo evita que o SDK abra conexão só para descobrir a região ao assinar.
_internal = Minio(settings.minio_endpoint, secure=settings.minio_secure, **_creds)
_public = Minio(settings.minio_public_endpoint, secure=settings.minio_public_secure, **_creds)


def build_object_key(org_id: uuid.UUID, doc_id: uuid.UUID) -> str:
    # O nome do arquivo do usuário NUNCA entra na chave (evita path tricks/colisões).
    return f"{org_id}/{doc_id}/original.pdf"


def parse_object_key(key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    parts = key.split("/")
    if len(parts) != 3 or parts[2] != "original.pdf":
        return None
    try:
        return uuid.UUID(parts[0]), uuid.UUID(parts[1])
    except ValueError:
        return None


def presign_upload(key: str, max_bytes: int) -> dict:
    """URL + campos de um POST pré-assinado. A policy trava chave, tipo e tamanho no servidor."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.upload_url_ttl_seconds)
    policy = PostPolicy(settings.minio_bucket, expires)
    policy.add_equals_condition("key", key)
    policy.add_equals_condition("Content-Type", "application/pdf")
    policy.add_content_length_range_condition(1, max_bytes)
    fields = dict(_public.presigned_post_policy(policy))
    fields.setdefault("key", key)
    fields.setdefault("Content-Type", "application/pdf")
    scheme = "https" if settings.minio_public_secure else "http"
    return {"url": f"{scheme}://{settings.minio_public_endpoint}/{settings.minio_bucket}", "fields": fields}


def _object_exists(key: str) -> bool:
    try:
        _internal.stat_object(settings.minio_bucket, key)
        return True
    except S3Error as exc:
        if exc.code in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
            return False
        raise


async def object_exists(key: str) -> bool:
    return await asyncio.to_thread(_object_exists, key)


def delete_object(key: str) -> None:
    _internal.remove_object(settings.minio_bucket, key)
