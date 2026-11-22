"""RLS no banco: mesmo uma query SEM filtro (bug de aplicação) não vaza dados entre organizações."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal, org_session
from app.models import Chunk

from .helpers import hash_embed, new_org, seed_document, whoami


async def _two_orgs(client):
    _, ha = await new_org(client, "OrgA")
    _, hb = await new_org(client, "OrgB")
    a, b = await whoami(client, ha), await whoami(client, hb)
    org_a, org_b = uuid.UUID(a["org_id"]), uuid.UUID(b["org_id"])
    doc_a = await seed_document(org_a, uuid.UUID(a["id"]), "a.pdf", ["texto secreto da organização A"])
    doc_b = await seed_document(org_b, uuid.UUID(b["id"]), "b.pdf", ["texto da organização B"])
    return org_a, org_b, doc_a, doc_b


async def test_select_without_where_only_returns_own_rows(client):
    org_a, org_b, _, _ = await _two_orgs(client)
    async with org_session(org_a) as s:
        orgs = {r[0] for r in (await s.execute(text("SELECT DISTINCT org_id FROM chunks"))).all()}
        docs = {r[0] for r in (await s.execute(text("SELECT DISTINCT org_id FROM documents"))).all()}
    assert orgs == {org_a} and docs == {org_a}


async def test_no_tenant_context_sees_nothing(client):
    await _two_orgs(client)
    async with SessionLocal() as s:  # sem app.org_id: fail-closed
        assert (await s.execute(text("SELECT count(*) FROM chunks"))).scalar() == 0
        assert (await s.execute(text("SELECT count(*) FROM documents"))).scalar() == 0


async def test_insert_for_another_org_is_rejected(client):
    org_a, org_b, _, doc_b = await _two_orgs(client)
    async with org_session(org_a) as s:
        s.add(Chunk(org_id=org_b, document_id=doc_b, chunk_index=99, page=1, content="injetado",
                    embedding=hash_embed("injetado"), embedding_model="test"))
        with pytest.raises(DBAPIError):  # WITH CHECK da policy
            await s.commit()


async def test_update_and_delete_cannot_touch_other_org(client):
    org_a, org_b, doc_a, _ = await _two_orgs(client)
    async with org_session(org_b) as s:
        await s.execute(text("UPDATE documents SET filename = 'hacked.pdf'"))
        await s.execute(text("DELETE FROM chunks"))
        await s.commit()
    async with org_session(org_a) as s:
        name = (await s.execute(text("SELECT filename FROM documents WHERE id = :i"), {"i": doc_a})).scalar()
        n_chunks = (await s.execute(text("SELECT count(*) FROM chunks WHERE document_id = :i"), {"i": doc_a})).scalar()
    assert name == "a.pdf" and n_chunks == 1
