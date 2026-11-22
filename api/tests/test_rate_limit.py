from app import rate_limit
from app.config import settings


class FakeRedis:
    def __init__(self):
        self.data: dict[str, int] = {}

    async def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key, seconds):
        return True


async def test_hit_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)
    results = [await rate_limit.hit("t", "u1", limit=3) for _ in range(4)]
    assert results[:3] == [None, None, None]
    assert isinstance(results[3], int) and 0 < results[3] <= 60
    assert await rate_limit.hit("t", "u2", limit=3) is None  # outro usuário não é afetado


async def test_login_is_rate_limited_by_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rl_auth_per_min", 2)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: FakeRedis())
    codes = []
    for _ in range(3):
        r = await client.post("/auth/login", data={"username": "x@x.test", "password": "senha-errada"})
        codes.append(r.status_code)
    assert codes == [401, 401, 429]


async def test_fails_open_when_redis_is_down(monkeypatch):
    class Broken:
        async def incr(self, key):
            raise ConnectionError("redis fora")
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: Broken())
    assert await rate_limit.hit("t", "u", limit=1) is None
