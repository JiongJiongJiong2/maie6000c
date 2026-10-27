"""add memeretrieve search backend

Revision ID: 20261027_0002
Revises: 20260713_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20261027_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("permission_note", sa.Text(), nullable=False),
        sa.Column("gif_path", sa.Text(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("corpus_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frame_count > 1", name="ck_reference_animated"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_table(
        "search_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_submission_key", sa.String(length=128), nullable=False),
        sa.Column("client_item_id", sa.String(length=128), nullable=True),
        sa.Column("input_path", sa.Text(), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("user_keywords", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_submission_key"),
    )
    op.create_table(
        "search_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("client_retry_key", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_kind", sa.String(length=20), nullable=True),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("corpus_version", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND result_kind IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND result_kind IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL AND finished_at IS NULL) OR "
            "(status = 'completed' AND result_kind IS NOT NULL "
            "AND result_kind IN ('candidates', 'no_candidates') "
            "AND error_code IS NULL AND error_detail IS NULL "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND started_at <= finished_at) OR "
            "(status = 'failed' AND result_kind IS NULL AND error_code IS NOT NULL "
            "AND error_detail IS NOT NULL AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND started_at <= finished_at)",
            name="ck_search_state",
        ),
        sa.CheckConstraint("attempt_no > 0", name="ck_search_attempt"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["search_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_retry_key"),
        sa.UniqueConstraint("request_id", "attempt_no", name="uq_search_attempt"),
    )
    op.create_index("ix_search_jobs_queue", "search_jobs", ["status", "created_at"], unique=False)
    op.create_index(
        "uq_search_active_request",
        "search_jobs",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("reference_asset_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("local_cache_path", sa.Text(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("cache_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frame_count > 1", name="ck_candidate_animated"),
        sa.CheckConstraint("rank BETWEEN 1 AND 3", name="ck_candidate_rank"),
        sa.CheckConstraint(
            "abs(similarity_score) < 1.0e308",
            name="ck_candidate_score_finite",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["search_jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["reference_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "job_id", name="uq_candidate_membership"),
        sa.UniqueConstraint("job_id", "rank", name="uq_candidate_rank"),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("client_review_key", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(decision = 'accept' AND candidate_id IS NOT NULL) OR "
            "(decision = 'reject_all' AND candidate_id IS NULL)",
            name="ck_review_decision",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "job_id"],
            ["candidates.id", "candidates.job_id"],
            name="fk_review_candidate_job",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["search_jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_review_key"),
    )
    op.create_index(
        op.f("ix_review_decisions_job_id"), "review_decisions", ["job_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_review_decisions_job_id"), table_name="review_decisions")
    op.drop_table("review_decisions")
    op.drop_table("candidates")
    op.drop_index(
        "uq_search_active_request",
        table_name="search_jobs",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_index("ix_search_jobs_queue", table_name="search_jobs")
    op.drop_table("search_jobs")
    op.drop_table("search_requests")
    op.drop_table("reference_assets")
