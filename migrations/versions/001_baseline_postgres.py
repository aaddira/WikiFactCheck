"""baseline postgres - create all tables from scratch

Revision ID: 001
Revises:
Create Date: 2026-07-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create users table first (base table, no dependencies)
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('wiki_username', sa.String(length=255)),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('qualification_passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('qualification_score', sa.Integer()),
        sa.Column('qualification_date', sa.DateTime()),
        sa.Column('test_submitted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('test_submission_date', sa.DateTime()),
        sa.Column('test_approved_by_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('test_approval_date', sa.DateTime()),
        sa.Column('max_annotations_cap', sa.Integer()),
        sa.Column('annotations_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('annotation_target', sa.Integer()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('last_login', sa.DateTime()),
        sa.Column('wiki_username_provided', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # Create datasets table (depends on users)
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('citation_type', sa.String(length=20), nullable=False, server_default='JOURNAL'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_user_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Create pairs table (depends on datasets)
    op.create_table(
        'pairs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pair_id', sa.String(length=255), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('citation_type', sa.String(length=20), nullable=False, server_default='JOURNAL'),
        sa.Column('article_title', sa.String(length=500)),
        sa.Column('research_domains', sa.String(length=500)),
        sa.Column('passage_text', sa.Text()),
        sa.Column('passage_word_count', sa.Integer()),
        sa.Column('passage_sentence_count', sa.Integer()),
        sa.Column('passage_context', sa.Text()),
        sa.Column('citation_title', sa.String(length=500)),
        sa.Column('citation_journal', sa.String(length=255)),
        sa.Column('citation_doi', sa.String(length=255)),
        sa.Column('citation_year', sa.String(length=10)),
        sa.Column('citation_authors', sa.String(length=1000)),
        sa.Column('citation_raw_text', sa.Text()),
        sa.Column('citation_source_url', sa.Text()),
        sa.Column('citation_raw_word_count', sa.Integer()),
        sa.Column('is_test_sample', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('correct_label', sa.String(length=50)),
        sa.Column('annotation_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pair_id', 'dataset_id', name='uq_pair_id_dataset_id')
    )
    op.create_index('ix_pairs_pair_id', 'pairs', ['pair_id'])

    # Create annotations table (depends on pairs and users)
    op.create_table(
        'annotations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pair_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=50), nullable=False),
        sa.Column('quote', sa.Text()),
        sa.Column('explanation', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['pair_id'], ['pairs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pair_id', 'user_id', name='uq_annotation_pair_user')
    )

    # Create claims table (depends on pairs and users)
    # NOTE: unique constraint on pair_id only (race condition fix)
    op.create_table(
        'claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pair_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('claimed_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['pair_id'], ['pairs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pair_id', name='uq_claim_pair_id')
    )

    # Create skips table (depends on pairs and users)
    op.create_table(
        'skips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pair_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['pair_id'], ['pairs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pair_id', 'user_id', name='uq_skip_pair_user')
    )

    # Create test_submissions table (depends on users and pairs)
    op.create_table(
        'test_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('pair_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=50)),
        sa.Column('quote', sa.Text()),
        sa.Column('explanation', sa.Text()),
        sa.Column('is_submitted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('submission_batch_id', sa.String(length=255)),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['pair_id'], ['pairs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'pair_id', 'submission_batch_id', name='uq_test_submission')
    )
    op.create_index('ix_test_submissions_user_id', 'test_submissions', ['user_id'])

    # Create config table (simple key-value store)
    op.create_table(
        'config',
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text()),
        sa.Column('updated_at', sa.DateTime()),
        sa.PrimaryKeyConstraint('key')
    )

    # Create audit_logs table (depends on users)
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('actor_user_id', sa.Integer()),
        sa.Column('actor_email', sa.String(length=255), nullable=False),
        sa.Column('target_type', sa.String(length=50)),
        sa.Column('target_id', sa.String(length=100)),
        sa.Column('details', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_audit_action_created', 'audit_logs', ['action', 'created_at'])


def downgrade():
    op.drop_index('ix_audit_action_created', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('config')
    op.drop_index('ix_test_submissions_user_id', table_name='test_submissions')
    op.drop_table('test_submissions')
    op.drop_table('skips')
    op.drop_table('claims')
    op.drop_table('annotations')
    op.drop_index('ix_pairs_pair_id', table_name='pairs')
    op.drop_table('pairs')
    op.drop_table('datasets')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
