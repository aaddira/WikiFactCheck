"""Clear legacy is_test_sample flags to migrate to new TestSampleSet system

Revision ID: 004
Revises: 003
Create Date: 2026-08-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    """Clear all is_test_sample=True flags so new versioned system is used exclusively."""
    # Update all pairs marked as is_test_sample=True to False
    op.execute("UPDATE pairs SET is_test_sample = FALSE WHERE is_test_sample = TRUE")


def downgrade():
    """No downgrade: clearing legacy data should not be reversed."""
    # Downgrade is not supported for data cleanup migrations
    pass
