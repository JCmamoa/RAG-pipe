from contextlib import contextmanager

import psycopg

from config import settings


def dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@contextmanager
def org_tx(org_id):
    """Transação com tenant fixado: o RLS vale para o worker também (papel rag_app).

    Commit ao sair do bloco; rollback se houver exceção.
    """
    with psycopg.connect(dsn()) as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
            yield conn


@contextmanager
def plain_tx():
    """Sem tenant. Só para tabelas globais (organizations)."""
    with psycopg.connect(dsn()) as conn:
        with conn.transaction():
            yield conn
