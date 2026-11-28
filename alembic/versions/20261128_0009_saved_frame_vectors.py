"""Optionally provision a derived saved-GIF frame index."""

from alembic import op

from services.common.config import get_settings
from services.retrieval.vector_store import provision_vector_tables

revision = "20261128_0009"
down_revision = "20261121_0008"
branch_labels = depends_on = None


def upgrade():
    if not op.get_context().as_sql and get_settings().vector_backend == "pgvector":
        provision_vector_tables(op.get_bind())


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS saved_frame_vectors")
        op.execute("DROP TABLE IF EXISTS saved_vector_versions")
