import hashlib
import math
import re
import uuid

from app.config import settings
from app.db import org_session
from app.models import Chunk, Document


def hash_embed(text: str, dim: int | None = None) -> list[float]:
    """Embedding de mentirinha: palavras iguais => vetores próximos. Suficiente para testar isolamento."""
    dim = dim or settings.embedding_dim
    vec = [0.0] * dim
    for tok in re.findall(r"\w+", text.lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def seed_document(org_id: uuid.UUID, user_id: uuid.UUID, filename: str, pages: list[str],
                        status: str = "ready") -> uuid.UUID:
    """Insere documento + chunks direto no banco (como o worker faria)."""
    doc_id = uuid.uuid4()
    async with org_session(org_id) as s:
        s.add(Document(id=doc_id, org_id=org_id, uploaded_by=user_id, filename=filename,
                       object_key=f"{org_id}/{doc_id}/original.pdf", content_type="application/pdf",
                       size_bytes=1000, status=status, page_count=len(pages)))
        await s.flush()
        for i, content in enumerate(pages):
            s.add(Chunk(org_id=org_id, document_id=doc_id, chunk_index=i, page=i + 1, content=content,
                        embedding=hash_embed(content), embedding_model="test"))
        await s.commit()
    return doc_id


async def new_org(client, name: str = "Org"):
    email = f"{uuid.uuid4().hex[:10]}@{name.lower()}.test"
    r = await client.post("/auth/register",
                          json={"org_name": name, "email": email, "password": "senha-forte-123"})
    assert r.status_code == 201, r.text
    return email, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def whoami(client, headers) -> dict:
    return (await client.get("/auth/me", headers=headers)).json()


async def new_member(client, admin_headers):
    email = f"{uuid.uuid4().hex[:10]}@member.test"
    r = await client.post("/users", headers=admin_headers, json={"email": email, "password": "senha-forte-123"})
    assert r.status_code == 201, r.text
    login = await client.post("/auth/login", data={"username": email, "password": "senha-forte-123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
