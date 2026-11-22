import uuid

from .helpers import new_org, seed_document, whoami


async def test_search_only_returns_own_org_documents(client):
    _, ha = await new_org(client, "OrgA")
    _, hb = await new_org(client, "OrgB")
    a, b = await whoami(client, ha), await whoami(client, hb)
    doc_a = await seed_document(uuid.UUID(a["org_id"]), uuid.UUID(a["id"]), "paris.pdf",
                                ["a capital da França é Paris"])
    doc_b = await seed_document(uuid.UUID(b["org_id"]), uuid.UUID(b["id"]), "bolo.pdf",
                                ["receita de bolo de chocolate com cobertura"])

    res_b = await client.post("/search", headers=hb, json={"query": "capital da França Paris", "k": 20})
    assert res_b.status_code == 200
    ids_b = {h["document_id"] for h in res_b.json()}
    assert str(doc_a) not in ids_b and str(doc_b) in ids_b

    # Pedir explicitamente o documento da outra org não funciona
    res = await client.post("/search", headers=hb,
                            json={"query": "capital da França", "document_ids": [str(doc_a)]})
    assert res.json() == []

    res_a = await client.post("/search", headers=ha, json={"query": "capital da França Paris"})
    assert res_a.json()[0]["document_id"] == str(doc_a)
    assert res_a.json()[0]["filename"] == "paris.pdf" and res_a.json()[0]["page"] == 1


async def test_search_ignores_documents_not_ready(client):
    _, h = await new_org(client)
    me = await whoami(client, h)
    await seed_document(uuid.UUID(me["org_id"]), uuid.UUID(me["id"]), "fila.pdf",
                        ["conteúdo ainda processando"], status="processing")
    res = await client.post("/search", headers=h, json={"query": "conteúdo processando"})
    assert res.json() == []


async def test_search_requires_auth(client):
    assert (await client.post("/search", json={"query": "x"})).status_code == 401
