"""Optionally provision the shared reference-GIF frame index."""

from alembic import op
from sqlalchemy import text

from services.common.config import get_settings
from services.retrieval.vector_store import provision_reference_tables

revision = "20261128_0010"
down_revision = "20261128_0009"
branch_labels = depends_on = None


def upgrade():
    if not op.get_context().as_sql and get_settings().vector_backend == "pgvector":
        provision_reference_tables(op.get_bind())


def downgrade():
    if op.get_context().as_sql:
        return
    connection = op.get_bind()
    if (
        connection.dialect.name == "postgresql"
        and connection.scalar(text("SELECT current_schema()")) == "public"
    ):
        op.execute("DROP TABLE IF EXISTS public.reference_frame_vectors")
        op.execute("DROP TABLE IF EXISTS public.reference_vector_generations")
