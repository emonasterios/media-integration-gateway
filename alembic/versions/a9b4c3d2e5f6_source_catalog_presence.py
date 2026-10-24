"""source catalog presence state

Revision ID: a9b4c3d2e5f6
Revises: f8a3b2c1d4e5
Create Date: 2026-10-23 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b4c3d2e5f6'
down_revision = 'f8a3b2c1d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch_op:
        batch_op.add_column(
            sa.Column('catalog_presence', sa.String(length=16), nullable=False, server_default='present')
        )
        batch_op.add_column(
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column('last_seen_run_id', sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column('missing_since', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column('consecutive_misses', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_column('consecutive_misses')
        batch_op.drop_column('missing_since')
        batch_op.drop_column('last_seen_run_id')
        batch_op.drop_column('last_seen_at')
        batch_op.drop_column('catalog_presence')
