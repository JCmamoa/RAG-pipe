from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str  # mesmo valor da API (rag_app); o prefixo +asyncpg é removido em db.py
    redis_url: str

    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False
    minio_region: str = "us-east-1"
    max_upload_mb: int = 50

    embedding_base_url: str = "http://ollama:11434/v1"
    embedding_api_key: str = "ollama"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_doc_prefix: str = ""
    embedding_batch_size: int = 16

    # Chunking: ~4 caracteres por token => 2400 chars ≈ 600 tokens, overlap 300 ≈ 12%
    chunk_size_chars: int = 2400
    chunk_overlap_chars: int = 300
    chunk_min_chars: int = 40

    max_pages: int = 2000
    ocr_enabled: bool = True
    ocr_langs: str = "por+eng"
    ocr_min_chars: int = 30  # página com menos texto que isso é tratada como imagem

    log_level: str = "INFO"


settings = Settings()
