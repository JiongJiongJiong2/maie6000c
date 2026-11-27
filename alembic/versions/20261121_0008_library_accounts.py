"""Add account credentials, revocable sessions and local owner setup."""

from alembic import op
from services.common.accounts import registry

revision = "20261121_0008"
down_revision = "20261118_0007"
branch_labels = depends_on = None


def upgrade():
    registry.create_all(op.get_bind())


def downgrade():
    from sqlalchemy import select
    from services.common.accounts import accounts

    if op.get_bind().execute(select(accounts.c.username).limit(1)).first():
        raise RuntimeError("Registered libraries require the account schema")
    registry.drop_all(op.get_bind())
