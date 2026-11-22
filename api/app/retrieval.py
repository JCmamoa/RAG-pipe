import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings


@dataclass
class Hit:
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page: int | None
    chunk_index: int
    content: str
    score: float


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


async def retrieve(session: AsyncSession, org_id: uuid.UUID, query_vec: list[float], k: int,
                   document_ids: list[uuid.UUID] | None = None) -> list[Hit]:
    """Busca vetorial (cosseno) restrita à organização.

    Defesa em profundidade: `c.org_id = :org_id` aqui E a policy de RLS no banco.
    `session` deve ser uma sessão com tenant (org_session / get_org_session).
    """
    # pgvector >= 0.8: sem varredura iterativa, o filtro pós-índice pode devolver menos que k.
    await session.execute(
        text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
             "set_config('hnsw.ef_search', :ef, true)"),
        {"ef": str(settings.retrieval_ef_search)})

    sql = """
        SELECT c.id, c.document_id, d.filename, c.page, c.chunk_index, c.content,
               1 - (c.embedding <=> CAST(:q AS vector)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.org_id = :org_id AND d.org_id = :org_id AND d.status = 'ready'
    """
    params: dict = {"q": vector_literal(query_vec), "org_id": org_id, "k": k}
    if document_ids:
        sql += " AND c.document_id = ANY(CAST(:doc_ids AS uuid[]))"
        params["doc_ids"] = list(document_ids)
    sql += " ORDER BY c.embedding <=> CAST(:q AS vector) LIMIT :k"

    rows = (await session.execute(text(sql), params)).all()
    return [Hit(chunk_id=r.id, document_id=r.document_id, filename=r.filename, page=r.page,
                chunk_index=r.chunk_index, content=r.content, score=float(r.score)) for r in rows]
