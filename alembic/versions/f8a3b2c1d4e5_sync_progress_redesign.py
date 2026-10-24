"""sync progress redesign: run phase/counters and catalog_sync_pages

Revision ID: f8a3b2c1d4e5
Revises: e7f2a1b3c4d5
Create Date: 2026-10-23 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a3b2c1d4e5'
down_revision: Union[str, Sequence[str], None] = 'e7f2a1b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_sync_runs") as batch_op:
        batch_op.add_column(
            sa.Column('phase', sa.String(length=32), nullable=False, server_default='queued')
        )
        batch_op.add_column(sa.Column('stop_reason', sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column('items_seen', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_unique', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_inserted', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_updated', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_unchanged', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_duplicate_in_run', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('items_rejected', sa.Integer(), nullable=False, server_default='0')
        )

    op.create_table(
        'catalog_sync_pages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'run_id',
            sa.String(length=36),
            sa.ForeignKey('catalog_sync_runs.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('page_url', sa.Text(), nullable=False),
        sa.Column('next_page_url', sa.Text(), nullable=True),
        sa.Column('page_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unique', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inserted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unchanged', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duplicate_in_run', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'committed_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint('run_id', 'page_number', name='uq_catalog_sync_pages_run_page'),
    )


def downgrade() -> None:
    op.drop_table("catalog_sync_pages")

    with op.batch_alter_table("catalog_sync_runs") as batch_op:
        batch_op.drop_column('items_rejected')
        batch_op.drop_column('items_duplicate_in_run')
        batch_op.drop_column('items_unchanged')
        batch_op.drop_column('items_updated')
        batch_op.drop_column('items_inserted')
        batch_op.drop_column('items_unique')
        batch_op.drop_column('items_seen')
        batch_op.drop_column('stop_reason')
        batch_op.drop_column('phase')
