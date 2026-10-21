"""Add per-user UI language and email language.

Revision ID: 007
Revises: 006
Create Date: 2026-10-21 12:00:00.000000

Existing users are backfilled to 'en' via the server default, so nothing about
their experience changes until they choose otherwise.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('language', sa.String(length=8), nullable=False, server_default='en'))
    op.add_column('users', sa.Column('email_language', sa.String(length=8), nullable=False, server_default='en'))


def downgrade():
    op.drop_column('users', 'email_language')
    op.drop_column('users', 'language')
