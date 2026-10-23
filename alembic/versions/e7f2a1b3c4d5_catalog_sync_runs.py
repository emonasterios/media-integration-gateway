"""catalog_sync_runs table

Revision ID: e7f2a1b3c4d5
Revises: d6e1f2a3b4c5
Create Date: 2026-10-22 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f2a1b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd6e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'catalog_sync_runs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('active_slot', sa.Integer(), nullable=True),
        sa.Column('checkpoint_path', sa.String(), nullable=True),
        sa.Column('pages_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('items_discovered', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.UniqueConstraint('active_slot', name='uq_catalog_sync_runs_active_slot'),
    )
    op.create_index('ix_catalog_sync_runs_status', 'catalog_sync_runs', ['status'])


def downgrade() -> None:
    op.drop_table('catalog_sync_runs')
