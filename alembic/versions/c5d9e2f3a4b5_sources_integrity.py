"""sources integrity cleanup and uniqueness

Revision ID: c5d9e2f3a4b5
Revises: b4c8d1e2f3a4
Create Date: 2026-10-21 20:55:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c5d9e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b4c8d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM sources WHERE media_id NOT IN (SELECT id FROM media);")
    op.execute(
        "DELETE FROM sources WHERE id NOT IN ("
        "SELECT MIN(id) FROM sources GROUP BY provider, url"
        ");"
    )
    with op.batch_alter_table("sources") as batch_op:
        batch_op.create_unique_constraint("uq_sources_provider_url", ["provider", "url"])


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_constraint("uq_sources_provider_url", type_="unique")
