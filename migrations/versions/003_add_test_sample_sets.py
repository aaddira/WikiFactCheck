"""Add TestSampleSet versioning tables

Revision ID: 003
Revises: 002
Create Date: 2026-08-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Create test_sample_sets table
    op.create_table(
        'test_sample_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=False),
        sa.Column('sample_count', sa.Integer(), default=0),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create test_sample_set_memberships table
    op.create_table(
        'test_sample_set_memberships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('test_set_id', sa.Integer(), nullable=False, index=True),
        sa.Column('pair_id', sa.Integer(), nullable=False, index=True),
        sa.Column('correct_label', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.ForeignKeyConstraint(['test_set_id'], ['test_sample_sets.id'], ),
        sa.ForeignKeyConstraint(['pair_id'], ['pairs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('test_set_id', 'pair_id', name='uq_test_set_pair')
    )

    # Create indices
    op.create_index('ix_test_sample_sets_is_active', 'test_sample_sets', ['is_active'])


def downgrade():
    op.drop_index('ix_test_sample_sets_is_active', table_name='test_sample_sets')
    op.drop_table('test_sample_set_memberships')
    op.drop_table('test_sample_sets')
