import uuid

from app.config import settings

from .helpers import new_member, new_org, seed_document, whoami

AUTH = lambda: {"Authorization": f"Bearer {settings.minio_webhook_token}"}  # noqa: E731


def _event(key: str, name: str = "s3:ObjectCreated:Post") -> dict:
    return {"EventName": name, "Key": f"{settings.minio_bucket}/{key}", "Records": [
        {"eventName": name, "s3": {"bucket": {"name": settings.minio_bucket}, "object": {"key": key}}}]}


async def _ticket(client, headers, filename="relatório.pdf", size=1234):
    r = await client.post("/documents", headers=headers, json={"filename": filename, "size_bytes": size})
    assert r.status_code == 201, r.text
    return r.json()


async def test_upload_ticket(client):
    _, h = await new_org(client)
    me = await whoami(client, h)
    body = await _ticket(client, h)
    doc, upload = body["document"], body["upload"]
    assert doc["status"] == "pending"
    assert upload["fields"]["key"] == f"{me['org_id']}/{doc['id']}/original.pdf"
    assert "policy" in upload["fields"] and upload["url"].endswith(f"/{settings.minio_bucket}")


async def test_rejects_non_pdf_and_oversize(client):
    _, h = await new_org(client)
    r = await client.post("/documents", headers=h, json={"filename": "x.exe", "size_bytes": 10})
    assert r.status_code == 422
    r = await client.post("/documents", headers=h,
                          json={"filename": "x.pdf", "size_bytes": (settings.max_upload_mb + 1) * 1024 * 1024})
    assert r.status_code == 413


async def test_confirm_is_idempotent(client, enqueued, monkeypatch):
    async def exists(key): return True
    monkeypatch.setattr("app.storage.object_exists", exists)
    _, h = await new_org(client)
    doc = (await _ticket(client, h))["document"]
    for _ in range(2):
        r = await client.post(f"/documents/{doc['id']}/confirm", headers=h)
        assert r.status_code == 202 and r.json()["status"] == "queued"
    assert len(enqueued) == 1


async def test_confirm_without_object_conflicts(client, monkeypatch):
    async def missing(key): return False
    monkeypatch.setattr("app.storage.object_exists", missing)
    _, h = await new_org(client)
    doc = (await _ticket(client, h))["document"]
    assert (await client.post(f"/documents/{doc['id']}/confirm", headers=h)).status_code == 409


async def test_webhook_requires_token_and_dedupes(client, enqueued):
    me_h = (await new_org(client))[1]
    me = await whoami(client, me_h)
    doc = (await _ticket(client, me_h))["document"]
    key = f"{me['org_id']}/{doc['id']}/original.pdf"

    assert (await client.post("/internal/minio-events", json=_event(key))).status_code == 401
    bad = {"Authorization": "Bearer errado"}
    assert (await client.post("/internal/minio-events", json=_event(key), headers=bad)).status_code == 401

    first = await client.post("/internal/minio-events", json=_event(key), headers=AUTH())
    again = await client.post("/internal/minio-events", json=_event(key), headers=AUTH())  # evento duplicado
    assert first.json() == {"enqueued": 1} and again.json() == {"enqueued": 0}
    assert len(enqueued) == 1
    ignored = await client.post("/internal/minio-events", json=_event("lixo/qualquer.txt"), headers=AUTH())
    assert ignored.json() == {"enqueued": 0}


async def test_webhook_cannot_cross_orgs(client, enqueued):
    ha, hb = (await new_org(client, "OrgA"))[1], (await new_org(client, "OrgB"))[1]
    a = await whoami(client, ha)
    doc_b = (await _ticket(client, hb))["document"]
    forged = f"{a['org_id']}/{doc_b['id']}/original.pdf"  # org de A + documento de B
    r = await client.post("/internal/minio-events", json=_event(forged), headers=AUTH())
    assert r.json() == {"enqueued": 0} and enqueued == []


async def test_documents_isolated_between_orgs(client):
    ha, hb = (await new_org(client, "OrgA"))[1], (await new_org(client, "OrgB"))[1]
    doc = (await _ticket(client, ha))["document"]
    assert (await client.get(f"/documents/{doc['id']}", headers=hb)).status_code == 404
    assert (await client.delete(f"/documents/{doc['id']}", headers=hb)).status_code == 404
    assert doc["id"] not in [d["id"] for d in (await client.get("/documents", headers=hb)).json()]
    assert doc["id"] in [d["id"] for d in (await client.get("/documents", headers=ha)).json()]


async def test_permissions_delete_and_reindex(client, enqueued, monkeypatch):
    monkeypatch.setattr("app.storage.delete_object", lambda key: None)
    _, admin = await new_org(client)
    me = await whoami(client, admin)
    member = await new_member(client, admin)
    doc_id = await seed_document(uuid.UUID(me["org_id"]), uuid.UUID(me["id"]), "x.pdf", ["conteúdo"])

    assert (await client.delete(f"/documents/{doc_id}", headers=member)).status_code == 403
    assert (await client.post(f"/documents/{doc_id}/reindex", headers=member)).status_code == 403

    r = await client.post(f"/documents/{doc_id}/reindex", headers=admin)
    assert r.status_code == 202 and r.json()["status"] == "queued" and len(enqueued) == 1
    assert (await client.delete(f"/documents/{doc_id}", headers=admin)).status_code == 204
