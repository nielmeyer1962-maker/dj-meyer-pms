"""add app_settings table and seed ITR12 deadlines

Revision ID: c2e75b9a4f31
Revises: a1c93f47e08b
Create Date: 2026-06-11 09:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2e75b9a4f31'
down_revision = 'a1c93f47e08b'
branch_labels = None
depends_on = None


def upgrade():
    app_settings = op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_app_settings_key'),
    )

    # Seed the ITR12 deadlines from the single source of truth shared with the tests (so
    # they cannot drift): non-provisional = 23 October, provisional = 20 January.
    from app.models.app_setting import APP_SETTING_SEED

    op.bulk_insert(app_settings, APP_SETTING_SEED)


def downgrade():
    op.drop_table('app_settings')
