"""Add confirmation email resend rate limiting field.

Revision ID: 005
Revises: 004
Create Date: 2026-09-03 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    # Add new column to track last confirmation resend time
    op.add_column('users', sa.Column('last_confirmation_resend_at', sa.DateTime(), nullable=True))


def downgrade():
    # Remove column
    op.drop_column('users', 'last_confirmation_resend_at')
