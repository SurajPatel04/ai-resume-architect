"""chat message ui meta

Carries whatever a question's `ui` needs beyond a list of chips — currently the
measure and unit behind a "metric" question. Nullable, so every message written
before this migration reads back exactly as it did.

Revision ID: a1c7f2e40b93
Revises: 5489fb321454
Create Date: 2026-08-01 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1c7f2e40b93'
down_revision: Union[str, Sequence[str], None] = '5489fb321454'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'chat_messages',
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'meta')
