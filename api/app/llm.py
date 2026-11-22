"""Clientes de embeddings e chat para qualquer API compatível com OpenAI (Ollama, OpenAI, vLLM...)."""
import json
from collections.abc import AsyncIterator

import httpx

from .config import settings


class LLMError(Exception):
    pass


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


async def embed(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    prefix = settings.embedding_query_prefix if is_query else ""
    payload = {"model": settings.embedding_model, "input": [prefix + t for t in texts]}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{settings.embedding_base_url}/embeddings", json=payload,
                                     headers=_headers(settings.embedding_api_key))
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"falha no serviço de embeddings: {exc}") from exc
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    vectors = [d["embedding"] for d in data]
    for vec in vectors:
        if len(vec) != settings.embedding_dim:
            raise LLMError(f"dimensão {len(vec)} != EMBEDDING_DIM={settings.embedding_dim} "
                           f"(modelo {settings.embedding_model})")
    return vectors


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Gera os pedaços de texto da resposta (SSE no formato OpenAI)."""
    payload = {"model": settings.llm_model, "messages": messages, "stream": True,
               "temperature": settings.llm_temperature}
    timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{settings.llm_base_url}/chat/completions", json=payload,
                                     headers=_headers(settings.llm_api_key)) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:300]
                    raise LLMError(f"LLM respondeu {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        choices = json.loads(data).get("choices") or []
                    except json.JSONDecodeError:
                        continue
                    if choices:
                        delta = (choices[0].get("delta") or {}).get("content")
                        if delta:
                            yield delta
    except httpx.HTTPError as exc:
        raise LLMError(f"falha no serviço de LLM: {exc}") from exc
