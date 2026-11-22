"""Testes de auth e isolamento entre organizações (rodam contra o Postgres do compose)."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.security import create_access_token


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def new_org(client, name="Org"):
    email = f"{uuid.uuid4().hex[:10]}@{name.lower()}.test"
    r = await client.post("/auth/register",
                          json={"org_name": name, "email": email, "password": "senha-forte-123"})
    assert r.status_code == 201, r.text
    return email, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_org_b_does_not_see_org_a_users(client):
    _, admin_a = await new_org(client, "OrgA")
    _, admin_b = await new_org(client, "OrgB")

    created = await client.post("/users", headers=admin_a,
                                json={"email": f"{uuid.uuid4().hex[:8]}@a.test", "password": "senha-forte-123"})
    assert created.status_code == 201
    victim_id = created.json()["id"]

    listing_b = await client.get("/users", headers=admin_b)
    assert victim_id not in [u["id"] for u in listing_b.json()]

    # Tentar alterar usuário de outra org retorna 404, sem vazar a existência do id.
    patch = await client.patch(f"/users/{victim_id}", headers=admin_b, json={"is_active": False})
    assert patch.status_code == 404


async def test_member_cannot_manage_users(client):
    _, admin = await new_org(client)
    member_email = f"{uuid.uuid4().hex[:8]}@m.test"
    await client.post("/users", headers=admin, json={"email": member_email, "password": "senha-forte-123"})
    login = await client.post("/auth/login", data={"username": member_email, "password": "senha-forte-123"})
    member = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/users", headers=member)).status_code == 403
    assert (await client.post("/users", headers=member,
                              json={"email": "x@x.test", "password": "senha-forte-123"})).status_code == 403


async def test_wrong_password_and_unknown_email_look_the_same(client):
    email, _ = await new_org(client)
    wrong = await client.post("/auth/login", data={"username": email, "password": "errada-errada"})
    unknown = await client.post("/auth/login", data={"username": "ninguem@x.test", "password": "errada-errada"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_token_with_foreign_org_is_rejected(client):
    """Mesmo com assinatura válida, org_id divergente do usuário no banco é recusado."""
    _, admin_a = await new_org(client, "OrgA")
    _, admin_b = await new_org(client, "OrgB")
    me_a = (await client.get("/auth/me", headers=admin_a)).json()
    me_b = (await client.get("/auth/me", headers=admin_b)).json()

    forged = create_access_token(uuid.UUID(me_a["id"]), uuid.UUID(me_b["org_id"]), "admin")
    r = await client.get("/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_deactivated_user_loses_access_immediately(client):
    _, admin = await new_org(client)
    email = f"{uuid.uuid4().hex[:8]}@d.test"
    created = (await client.post("/users", headers=admin,
                                 json={"email": email, "password": "senha-forte-123"})).json()
    login = await client.post("/auth/login", data={"username": email, "password": "senha-forte-123"})
    member = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/auth/me", headers=member)).status_code == 200

    await client.patch(f"/users/{created['id']}", headers=admin, json={"is_active": False})
    assert (await client.get("/auth/me", headers=member)).status_code == 401
