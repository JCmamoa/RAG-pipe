"""Rate limit por janela fixa de 60 s no Redis.

Janela fixa permite rajada de até 2x o limite na virada da janela. Para um limite mais
suave, troque por sliding window (ZSET) ou token bucket (script Lua).
Falha aberta: se o Redis cair, a API segue funcionando e registra um warning.
"""
import logging
import time

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request

from .config import settings
from .deps import get_current_user
from .metrics import RATE_LIMITED
from .models import User

log = logging.getLogger(__name__)
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def hit(scope: str, ident: str, limit: int, window: int = 60) -> int | None:
    """Registra uma chamada. Retorna None se permitida, ou segundos até liberar."""
    if not settings.rate_limit_enabled:
        return None
    now = int(time.time())
    key = f"rl:{scope}:{ident}:{now // window}"
    try:
        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window + 1)
    except Exception:
        log.warning("rate limit indisponível (Redis); liberando", exc_info=True)
        return None
    if count > limit:
        RATE_LIMITED.labels(scope).inc()
        return window - (now % window)
    return None


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(429, "Muitas requisições. Tente novamente em instantes.",
                         headers={"Retry-After": str(retry_after)})


def limit_by_ip(scope: str, setting_name: str):
    async def dependency(request: Request):
        ident = request.client.host if request.client else "unknown"
        retry = await hit(scope, ident, getattr(settings, setting_name))
        if retry:
            raise _too_many(retry)
    return dependency


def limit_by_user(scope: str, setting_name: str):
    async def dependency(user: User = Depends(get_current_user)):
        retry = await hit(scope, str(user.id), getattr(settings, setting_name))
        if retry:
            raise _too_many(retry)
    return dependency
