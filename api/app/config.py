from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infra
    database_url: str
    migration_database_url: str | None = None
    redis_url: str
    db_null_pool: bool = False  # testes: evita pool preso a outro event loop

    # --- auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30

    # --- object storage
    minio_endpoint: str = "minio:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False
    minio_public_secure: bool = False
    minio_region: str = "us-east-1"
    minio_webhook_token: str
    max_upload_mb: int = 50
    upload_url_ttl_seconds: int = 600

    # --- embeddings / LLM (API compatível com OpenAI: Ollama, OpenAI, vLLM...)
    embedding_base_url: str = "http://ollama:11434/v1"
    embedding_api_key: str = "ollama"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024  # precisa casar com vector(N) da migration
    embedding_query_prefix: str = ""
    llm_base_url: str = "http://ollama:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "llama3.2:3b"
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 120

    # --- busca / chat
    retrieval_top_k: int = 6
    retrieval_ef_search: int = 80
    chat_history_turns: int = 6
    max_question_chars: int = 2000
    ws_auth_timeout_seconds: int = 10

    # --- rate limit (janela fixa de 60 s)
    rate_limit_enabled: bool = True
    rl_auth_per_min: int = 10      # por IP
    rl_upload_per_min: int = 20    # por usuário
    rl_search_per_min: int = 60    # por usuário
    rl_chat_per_min: int = 20      # por usuário

    log_level: str = "INFO"


settings = Settings()
