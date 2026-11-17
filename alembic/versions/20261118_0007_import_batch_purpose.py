"""Persist the size policy selected when an import batch is created."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0007"
down_revision = "20261117_0006"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("library_import_batches") as batch:
        batch.add_column(
            sa.Column("purpose", sa.String(16), nullable=False, server_default="upload")
        )
        batch.create_check_constraint(
            "ck_import_batch_purpose", "purpose IN ('upload', 'backup_restore')"
        )


def downgrade():
    with op.batch_alter_table("library_import_batches") as batch:
        batch.drop_constraint("ck_import_batch_purpose", type_="check")
        batch.drop_column("purpose")
