import dataclasses

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..deps import get_current_user, get_org_session
from ..models import User
from ..rate_limit import limit_by_user
from ..retrieval import retrieve
from ..schemas import SearchHitOut, SearchIn

router = APIRouter(tags=["search"])


@router.post("/search", response_model=list[SearchHitOut],
             dependencies=[Depends(limit_by_user("search", "rl_search_per_min"))])
async def search(body: SearchIn, user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_org_session)):
    """Busca semântica nos documentos (prontos) da organização do usuário logado."""
    try:
        vec = (await llm.embed([body.query], is_query=True))[0]
    except llm.LLMError:
        raise HTTPException(502, "Serviço de embeddings indisponível")
    hits = await retrieve(session, user.org_id, vec, body.k, body.document_ids)
    return [dataclasses.asdict(h) for h in hits]
