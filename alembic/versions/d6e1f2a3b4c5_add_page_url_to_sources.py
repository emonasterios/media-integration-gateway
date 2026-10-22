"""add page_url to sources

Revision ID: d6e1f2a3b4c5
Revises: c5d9e2f3a4b5
Create Date: 2026-10-22 08:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c5d9e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('page_url', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sources') as batch_op:
        batch_op.drop_column('page_url')
