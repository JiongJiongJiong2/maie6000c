"""meme50-v2 profile, verified drafts, progress and generic media.

Legacy GIF rows keep their original IDs, foreign keys, SHA and file paths.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0004"
down_revision = "20261109_0003"
branch_labels = depends_on = None

REQUEST = [
    sa.Column("search_profile", sa.String(30), nullable=False, server_default="legacy"),
    sa.Column("target_count", sa.Integer(), nullable=False, server_default="3"),
    sa.Column("input_metadata", sa.JSON()),
]
JOB = [
    sa.Column("search_profile", sa.String(30), nullable=False, server_default="legacy"),
    sa.Column("target_count", sa.Integer(), nullable=False, server_default="3"),
    sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
    sa.Column("analysis", sa.JSON()),
    sa.Column("progress", sa.JSON(), nullable=False, server_default="{}"),
    sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("result_revision", sa.String(64)),
    sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.false()),
]
MEDIA = [
    sa.Column("media_format", sa.String(10), nullable=False, server_default="GIF"),
    sa.Column("mime_type", sa.String(40), nullable=False, server_default="image/gif"),
    sa.Column("media_kind", sa.String(12), nullable=False, server_default="animated"),
    sa.Column("width", sa.Integer()),
    sa.Column("height", sa.Integer()),
    sa.Column("byte_size", sa.Integer()),
    sa.Column("duration_ms", sa.Integer()),
    sa.Column("content_group_id", sa.String(64)),
    sa.Column("preview_path", sa.Text()),
]


def upgrade():
    for table, columns in [
        ("search_requests", REQUEST),
        ("search_jobs", JOB),
        ("candidates", MEDIA),
    ]:
        for column in columns:
            op.add_column(table, column)
    with op.batch_alter_table("candidates") as batch:
        batch.drop_constraint("ck_candidate_rank", type_="check")
        batch.drop_constraint("ck_candidate_animated", type_="check")
        batch.create_check_constraint("ck_candidate_rank", "rank BETWEEN 1 AND 50")
        batch.create_check_constraint("ck_candidate_animated", "frame_count >= 1")
        batch.create_check_constraint(
            "ck_candidate_kind",
            "(frame_count = 1 AND media_kind = 'static') OR "
            "(frame_count > 1 AND media_kind = 'animated')",
        )
        batch.create_check_constraint(
            "ck_candidate_format",
            "(media_format = 'GIF' AND mime_type = 'image/gif') OR "
            "(media_format = 'PNG' AND mime_type = 'image/png') OR "
            "(media_format = 'JPEG' AND mime_type = 'image/jpeg') OR "
            "(media_format = 'WEBP' AND mime_type = 'image/webp')",
        )
        batch.create_unique_constraint("uq_candidate_content_group", ["job_id", "content_group_id"])
    op.create_table(
        "meme_candidate_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("search_jobs.id"), nullable=False, index=True
        ),
        sa.Column("draft_key", sa.String(64), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("preview_path", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "draft_key", name="uq_meme_draft_key"),
    )
    op.create_table(
        "meme_progress_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("search_jobs.id"), nullable=False, index=True
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "seq", name="uq_meme_event_sequence"),
    )
    op.execute(
        "UPDATE search_jobs SET result_count = "
        "(SELECT count(*) FROM candidates WHERE job_id = search_jobs.id)"
    )


def downgrade():
    connection = op.get_bind()
    incompatible = connection.execute(
        sa.text(
            "SELECT count(*) FROM candidates WHERE rank > 3 "
            "OR frame_count = 1 OR media_format <> 'GIF'"
        )
    ).scalar()
    requests = connection.execute(
        sa.text("SELECT count(*) FROM search_requests WHERE search_profile <> 'legacy'")
    ).scalar()
    if incompatible or requests:
        raise RuntimeError(
            "Cannot downgrade meme50 data to legacy; export/archive requests first. "
            "No data was deleted."
        )
    op.drop_table("meme_progress_events")
    op.drop_table("meme_candidate_drafts")
    with op.batch_alter_table("candidates") as batch:
        for name in [
            "ck_candidate_kind",
            "ck_candidate_format",
            "ck_candidate_rank",
            "ck_candidate_animated",
        ]:
            batch.drop_constraint(name, type_="check")
        batch.drop_constraint("uq_candidate_content_group", type_="unique")
        batch.create_check_constraint("ck_candidate_rank", "rank BETWEEN 1 AND 3")
        batch.create_check_constraint("ck_candidate_animated", "frame_count > 1")
    for table, columns in [
        ("candidates", MEDIA),
        ("search_jobs", JOB),
        ("search_requests", REQUEST),
    ]:
        for column in reversed(columns):
            op.drop_column(table, column.name)
