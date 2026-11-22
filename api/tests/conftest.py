import os

# Antes de importar qualquer módulo de `app` (as settings são lidas no import).
os.environ["DB_NULL_POOL"] = "true"        # sem pool preso a outro event loop
os.environ["RATE_LIMIT_ENABLED"] = "false"  # test_rate_limit liga de volta com Redis falso

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import llm  # noqa: E402
from app.main import app  # noqa: E402

from .helpers import hash_embed  # noqa: E402


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def enqueued(monkeypatch):
    """Nenhum teste fala com Celery/Redis: capturamos as chamadas de enfileiramento."""
    calls: list[tuple] = []
    monkeypatch.setattr("app.ingestion.enqueue_ingestion", lambda doc_id, org_id: calls.append((doc_id, org_id)))
    return calls


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """Embeddings determinísticos (bag-of-words) e LLM falso. Guarda os prompts recebidos."""
    prompts: list[list[dict]] = []

    async def fake_embed(texts, *, is_query=False):
        return [hash_embed(t) for t in texts]

    async def fake_stream(messages):
        prompts.append(messages)
        for piece in ("Resposta ", "baseada ", "no contexto [1]."):
            yield piece

    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    return prompts
