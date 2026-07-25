"""create chat models

Revision ID: 5489fb321454
Revises: 6f26eaff3359
Create Date: 2026-07-25 23:22:14.465997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

                                        
revision: str = '5489fb321454'
down_revision: Union[str, Sequence[str], None] = '6f26eaff3359'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
                                                                 
    op.create_table('chat_sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)
    op.create_index('ix_chat_sessions_user_updated', 'chat_sessions', ['user_id', 'updated_at'], unique=False)
    op.create_table('chat_messages',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('ui', sa.String(length=16), nullable=True),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chat_messages_session_id', 'chat_messages', ['session_id', 'id'], unique=False)
                                  


def downgrade() -> None:
    """Downgrade schema."""
                                                                 
    op.drop_index('ix_chat_messages_session_id', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_chat_sessions_user_updated', table_name='chat_sessions')
    op.drop_index(op.f('ix_chat_sessions_user_id'), table_name='chat_sessions')
    op.drop_table('chat_sessions')
                                  
