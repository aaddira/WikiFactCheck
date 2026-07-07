"""Add email confirmation fields to users table.

Revision ID: 002
Revises: 001
Create Date: 2026-07-06 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to users table
    op.add_column('users', sa.Column('email_confirmed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('confirmation_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('confirmation_token_expires_at', sa.DateTime(), nullable=True))

    # Create index on confirmation_token for faster lookups
    op.create_index('idx_confirmation_token', 'users', ['confirmation_token'], unique=False)

    # Mark all existing users as confirmed (historical data - they're already in the system)
    op.execute('UPDATE users SET email_confirmed = true WHERE email_confirmed IS NULL')


def downgrade():
    # Remove index
    op.drop_index('idx_confirmation_token', table_name='users')

    # Remove columns
    op.drop_column('users', 'confirmation_token_expires_at')
    op.drop_column('users', 'confirmation_token')
    op.drop_column('users', 'email_confirmed')
