"""Persist private library activation and per-file import receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0005"
down_revision = "20261111_0004"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "library_activation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.CheckConstraint("id = 1"),
    )
    op.create_table(
        "library_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_batch_key", sa.String(128), unique=True, nullable=False),
        sa.Column("manifest_sha", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "library_import_items",
        sa.Column(
            "batch_id", sa.String(36), sa.ForeignKey("library_import_batches.id"), primary_key=True
        ),
        sa.Column("client_item_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("saved_assets.id")),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint("status IN ('waiting', 'imported', 'duplicate', 'rejected')"),
        sa.CheckConstraint("(asset_id IS NOT NULL) = (status IN ('imported', 'duplicate'))"),
    )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT id FROM library_activation")).first():
        raise RuntimeError("Cannot remove the privacy marker from an activated library")
    op.drop_table("library_import_items")
    op.drop_table("library_import_batches")
    op.drop_table("library_activation")
