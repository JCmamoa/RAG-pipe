import os
import tempfile

from minio import Minio

from config import settings
from extract import ExtractionError

_client = Minio(settings.minio_endpoint, access_key=settings.minio_root_user,
                secret_key=settings.minio_root_password, secure=settings.minio_secure,
                region=settings.minio_region)


def download_to_temp(key: str) -> str:
    """Baixa o objeto para um arquivo temporário (nunca carrega o PDF inteiro na memória)."""
    size = _client.stat_object(settings.minio_bucket, key).size
    if size > settings.max_upload_mb * 1024 * 1024:
        raise ExtractionError("Arquivo acima do limite de tamanho")
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        _client.fget_object(settings.minio_bucket, key, path)
    except Exception:
        os.unlink(path)
        raise
    return path


def delete_object(key: str) -> None:
    _client.remove_object(settings.minio_bucket, key)
