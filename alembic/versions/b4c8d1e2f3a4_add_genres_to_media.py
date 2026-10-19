"""add genres to media

Revision ID: b4c8d1e2f3a4
Revises: a4b9a06fc210
Create Date: 2026-10-19 00:24:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c8d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a4b9a06fc210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('media', sa.Column('genres', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('media', 'genres')
