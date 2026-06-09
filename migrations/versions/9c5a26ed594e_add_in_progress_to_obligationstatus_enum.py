"""add IN_PROGRESS to obligationstatus enum

Revision ID: 9c5a26ed594e
Revises: 9766be8a3a42
Create Date: 2026-06-09 06:41:02.073743

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c5a26ed594e'
down_revision = '9766be8a3a42'
branch_labels = None
depends_on = None


def upgrade():
    # obligationstatus is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block, so step outside Alembic's wrapping transaction.
    # IN_PROGRESS sits between PENDING and SUBMITTED in the lifecycle. IF NOT EXISTS
    # keeps the migration idempotent if partially applied.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE obligationstatus ADD VALUE IF NOT EXISTS 'IN_PROGRESS' "
            "BEFORE 'SUBMITTED'"
        )


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # IN_PROGRESS. Any IN_PROGRESS rows fall back to PENDING — its open,
    # not-yet-submitted predecessor. This recreate is transactional (only ADD VALUE
    # needs autocommit), so it runs inside Alembic's normal transaction.
    op.execute("ALTER TYPE obligationstatus RENAME TO obligationstatus_old")
    op.execute(
        "CREATE TYPE obligationstatus AS ENUM ('PENDING', 'SUBMITTED', 'PAID', 'EXEMPT')"
    )
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN status TYPE obligationstatus "
        "USING (CASE WHEN status::text = 'IN_PROGRESS' THEN 'PENDING' "
        "ELSE status::text END)::obligationstatus"
    )
    op.execute("DROP TYPE obligationstatus_old")
