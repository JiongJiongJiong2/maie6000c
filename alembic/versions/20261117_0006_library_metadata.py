"""Store opt-in annotation, manual edits, and similarity scan coverage."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0006"
down_revision = "20261117_0005"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "library_asset_metadata",
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("saved_assets.id"), primary_key=True),
        sa.Column("title", sa.String(200)),
        sa.Column("manual", sa.JSON(), nullable=False),
        sa.Column("annotation", sa.JSON()),
        sa.Column("annotation_status", sa.String(16), nullable=False),
        sa.Column("annotation_attempt", sa.Integer(), nullable=False),
        sa.Column("annotation_version", sa.String(200)),
        sa.Column("annotation_sha", sa.String(64)),
        sa.Column("annotation_error", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "annotation_status IN ('not_requested','pending','running','ready','failed')"
        ),
    )
    op.create_index(
        "ix_library_annotation_queue", "library_asset_metadata", ["annotation_status", "updated_at"]
    )
    op.create_table(
        "library_similarity_scans",
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("saved_assets.id"), primary_key=True),
        sa.Column("matches", sa.JSON(), nullable=False),
        sa.Column("compared", sa.Integer(), nullable=False),
        sa.Column("considered", sa.Integer(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("library_similarity_scans")
    op.drop_table("library_asset_metadata")
