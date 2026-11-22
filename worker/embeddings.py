import httpx

from config import settings


class EmbeddingConfigError(Exception):
    """Configuração incompatível (ex.: dimensão do modelo != vector(N)). Não adianta retentar."""


def embed_all(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"}
    with httpx.Client(timeout=120) as client:
        for start in range(0, len(texts), settings.embedding_batch_size):
            batch = [settings.embedding_doc_prefix + t for t in texts[start:start + settings.embedding_batch_size]]
            resp = client.post(f"{settings.embedding_base_url}/embeddings", headers=headers,
                               json={"model": settings.embedding_model, "input": batch})
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            if len(data) != len(batch):
                raise EmbeddingConfigError("o serviço devolveu menos embeddings do que o enviado")
            for item in data:
                if len(item["embedding"]) != settings.embedding_dim:
                    raise EmbeddingConfigError(
                        f"dimensão {len(item['embedding'])} != EMBEDDING_DIM={settings.embedding_dim} "
                        f"(modelo {settings.embedding_model})")
                vectors.append(item["embedding"])
    return vectors


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
