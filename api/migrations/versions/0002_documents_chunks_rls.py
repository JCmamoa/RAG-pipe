"""documents + chunks (pgvector HNSW) + RLS + grants do papel rag_app

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024  # precisa casar com EMBEDDING_DIM. Trocar de modelo/dimensão = nova migration + reindex.

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("object_key", name="uq_documents_object_key"),
        sa.CheckConstraint("status IN ('pending','queued','processing','ready','failed')",
                           name="ck_documents_status"),
    )
    op.create_index("ix_documents_org_id", "documents", ["org_id"])
    op.create_index("ix_documents_org_status", "documents", ["org_id", "status"])

    op.execute(f"""
        CREATE TABLE chunks (
            id              BIGSERIAL PRIMARY KEY,
            org_id          UUID NOT NULL REFERENCES organizations(id),
            document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index     INT  NOT NULL,
            page            INT,
            content         TEXT NOT NULL,
            embedding       vector({EMBEDDING_DIM}) NOT NULL,
            embedding_model VARCHAR(100) NOT NULL,
            CONSTRAINT uq_chunks_doc_idx UNIQUE (document_id, chunk_index)
        )
    """)
    op.execute("CREATE INDEX ix_chunks_org_id ON chunks (org_id)")
    op.execute("CREATE INDEX ix_chunks_document_id ON chunks (document_id)")
    op.execute("""
        CREATE INDEX ix_chunks_embedding_hnsw ON chunks
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)

    # ---- Row-Level Security: fail-closed. Sem app.org_id na transação, nenhuma linha é visível.
    for table in ("documents", "chunks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # vale até para o dono
        op.execute(f"""
            CREATE POLICY org_isolation ON {table}
            USING (org_id = {TENANT})
            WITH CHECK (org_id = {TENANT})
        """)

    # ---- Privilégios do papel de runtime (criado em db/init/01-app-role.sh)
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_app') THEN
            GRANT USAGE ON SCHEMA public TO rag_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, users, documents, chunks TO rag_app;
            GRANT USAGE, SELECT ON SEQUENCE chunks_id_seq TO rag_app;
          ELSE
            RAISE WARNING 'papel rag_app não existe: recrie o volume (docker compose down -v)';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunks")
    op.drop_table("documents")
