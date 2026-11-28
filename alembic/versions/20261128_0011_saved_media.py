"""Preserve the original format of saved search results."""

import sqlalchemy as sa
from alembic import op

revision = "20261128_0011"
down_revision = "20261128_0010"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("saved_assets") as table:
        table.add_column(
            sa.Column("media_format", sa.String(10), nullable=False, server_default="GIF")
        )
        table.drop_constraint("ck_saved_asset_animated", type_="check")
        table.create_check_constraint("ck_saved_asset_frames", "frame_count >= 1")
        table.create_check_constraint(
            "ck_saved_asset_format", "media_format IN ('GIF', 'PNG', 'JPEG', 'WEBP')"
        )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM saved_assets WHERE media_format <> 'GIF' OR frame_count < 2")
    ):
        raise RuntimeError(
            "The previous schema cannot represent saved static images or non-GIF animations."
        )
    with op.batch_alter_table("saved_assets") as table:
        table.drop_constraint("ck_saved_asset_format", type_="check")
        table.drop_constraint("ck_saved_asset_frames", type_="check")
        table.create_check_constraint("ck_saved_asset_animated", "frame_count > 1")
        table.drop_column("media_format")
