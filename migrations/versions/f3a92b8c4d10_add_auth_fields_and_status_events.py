"""add staff auth fields, unique email, and status_events audit table

Revision ID: f3a92b8c4d10
Revises: c2e75b9a4f31
Create Date: 2026-06-12 06:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a92b8c4d10'
down_revision = 'c2e75b9a4f31'
branch_labels = None
depends_on = None


def upgrade():
    # Staff auth fields. is_admin carries a server_default so existing rows backfill to
    # False without a NULL violation; the model keeps a Python-side default too.
    op.add_column('staff', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column(
        'staff',
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Email keys login, so it must be unique. Postgres allows many NULLs under a unique
    # constraint, so emailless staff don't collide.
    op.create_unique_constraint('uq_staff_email', 'staff', ['email'])

    op.create_table(
        'status_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('instance_id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=20), nullable=False),
        sa.Column('from_value', sa.String(length=50), nullable=True),
        sa.Column('to_value', sa.String(length=50), nullable=True),
        sa.Column('actor_staff_id', sa.Integer(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['actor_staff_id'], ['staff.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_status_events_kind_instance', 'status_events', ['kind', 'instance_id'], unique=False
    )


def downgrade():
    op.drop_index('ix_status_events_kind_instance', table_name='status_events')
    op.drop_table('status_events')
    op.drop_constraint('uq_staff_email', 'staff', type_='unique')
    op.drop_column('staff', 'is_admin')
    op.drop_column('staff', 'password_hash')
