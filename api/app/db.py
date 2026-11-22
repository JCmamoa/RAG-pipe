import uuid
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from .config import settings

_kwargs = {"poolclass": NullPool} if settings.db_null_pool else {"pool_pre_ping": True}
engine = create_async_engine(settings.database_url, **_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _register_vector_codec(dbapi_conn, _record):
    """asyncpg não conhece o tipo `vector`: trafegamos como texto ('[0.1,0.2,...]')."""
    async def setup(conn):
        await conn.set_type_codec("vector", encoder=str, decoder=str, schema="public", format="text")
    dbapi_conn.run_async(setup)


@event.listens_for(Session, "after_begin")
def _apply_tenant(session, _transaction, connection):
    """Toda transação de uma sessão com info['org_id'] já nasce com app.org_id fixado.

    Vale também depois de session.commit() (a próxima transação reaplica). set_config(..., true)
    equivale a SET LOCAL: o valor morre no fim da transação e não vaza pelo pool.
    """
    org_id = session.info.get("org_id")
    if org_id:
        connection.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": org_id})


async def get_session():
    """Sessão SEM tenant. Só para auth e tabelas globais (users, organizations)."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def org_session(org_id: uuid.UUID):
    """Sessão com tenant: as policies de RLS de documents/chunks passam a valer.

    Quem escreve deve chamar `await session.commit()`; ao sair, o que não foi
    commitado sofre rollback.
    """
    async with SessionLocal(info={"org_id": str(org_id)}) as session:
        yield session
