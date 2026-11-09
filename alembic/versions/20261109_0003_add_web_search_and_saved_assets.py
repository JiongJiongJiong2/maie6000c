"""add web search jobs, saved assets, and execution records

Revision ID: 20261109_0003
Revises: 20261027_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20261109_0003"
down_revision = "20261027_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("gif_path", sa.Text(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("index_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("index_version", sa.String(length=100), nullable=True),
        sa.Column("index_error", sa.String(length=1000), nullable=True),
        sa.Column("index_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("frame_count > 1", name="ck_saved_asset_animated"),
        sa.CheckConstraint(
            "index_status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_saved_asset_index_status",
        ),
        sa.CheckConstraint("index_attempts >= 0", name="ck_saved_asset_index_attempts"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(
        "ix_saved_assets_index_queue",
        "saved_assets",
        ["index_status", "created_at"],
        unique=False,
        postgresql_where=sa.text("index_status = 'pending'"),
        sqlite_where=sa.text("index_status = 'pending'"),
    )

    with op.batch_alter_table("search_jobs") as batch:
        batch.add_column(
            sa.Column("job_kind", sa.String(length=20), server_default="local", nullable=False)
        )
        batch.add_column(
            sa.Column("stage", sa.String(length=30), server_default="pending", nullable=False)
        )
        batch.add_column(sa.Column("description", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("client_search_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("retry_of_job_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_search_jobs_retry_of_job_id", "search_jobs", ["retry_of_job_id"], ["id"]
        )
        batch.create_unique_constraint(
            "uq_search_jobs_client_search_key", ["client_search_key"]
        )

    with op.batch_alter_table("candidates") as batch:
        batch.alter_column(
            "reference_asset_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch.add_column(sa.Column("saved_asset_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("media_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("image_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("provider", sa.String(length=50), nullable=True))
        batch.create_foreign_key(
            "fk_candidates_saved_asset_id", "saved_assets", ["saved_asset_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_candidate_origin",
            "(reference_asset_id IS NOT NULL AND source_url IS NULL) OR "
            "(reference_asset_id IS NULL AND source_url IS NOT NULL)",
        )

    op.create_table(
        "search_executions",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("agent_version", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("stop_reason", sa.String(length=100), nullable=False),
        sa.Column("search_calls", sa.Integer(), nullable=False),
        sa.Column("planner_calls", sa.Integer(), nullable=False),
        sa.Column("downloads_used", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["search_jobs.id"]),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "candidate_saves",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("saved_asset_id", sa.String(length=36), nullable=False),
        sa.Column("client_save_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.ForeignKeyConstraint(["saved_asset_id"], ["saved_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "client_save_key"),
        sa.UniqueConstraint("client_save_key"),
    )


def downgrade() -> None:
    op.drop_table("candidate_saves")
    op.drop_table("search_executions")
    with op.batch_alter_table("candidates") as batch:
        batch.drop_constraint("ck_candidate_origin", type_="check")
        batch.drop_constraint("fk_candidates_saved_asset_id", type_="foreignkey")
        batch.drop_column("provider")
        batch.drop_column("image_url")
        batch.drop_column("source_url")
        batch.drop_column("media_sha256")
        batch.drop_column("saved_asset_id")
        batch.alter_column(
            "reference_asset_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
    with op.batch_alter_table("search_jobs") as batch:
        batch.drop_constraint("uq_search_jobs_client_search_key", type_="unique")
        batch.drop_constraint("fk_search_jobs_retry_of_job_id", type_="foreignkey")
        batch.drop_column("retry_of_job_id")
        batch.drop_column("client_search_key")
        batch.drop_column("description")
        batch.drop_column("stage")
        batch.drop_column("job_kind")
    op.drop_index("ix_saved_assets_index_queue", table_name="saved_assets")
    op.drop_table("saved_assets")
