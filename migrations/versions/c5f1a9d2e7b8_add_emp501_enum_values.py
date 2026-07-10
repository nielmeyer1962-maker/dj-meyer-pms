"""add EMP501_INTERIM and EMP501_ANNUAL to obligationtype enum

Revision ID: c5f1a9d2e7b8
Revises: b3e8d1a6c402
Create Date: 2026-06-13 05:30:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c5f1a9d2e7b8'
down_revision = 'b3e8d1a6c402'
branch_labels = None
depends_on = None


def upgrade():
    # obligationtype is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run inside
    # a transaction block, so step outside Alembic's wrapping transaction. No positional
    # BEFORE/AFTER — ObligationType order carries no meaning. IF NOT EXISTS keeps the
    # migration idempotent if partially applied. Both EMP501 reconciliations are file-only
    # (absent from _PAYMENT_LEG_TYPES), so no model/data change beyond the enum values.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'EMP501_INTERIM'")
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'EMP501_ANNUAL'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without the
    # two EMP501 values. Any rows of those types would block the cast; none are expected at
    # downgrade time (this revision introduces them), so delete them first to keep the
    # downgrade total. This recreate is transactional, so it runs inside Alembic's normal
    # transaction.
    op.execute(
        "DELETE FROM obligation_instances "
        "WHERE obligation_type IN ('EMP501_INTERIM', 'EMP501_ANNUAL')"
    )
    op.execute("ALTER TYPE obligationtype RENAME TO obligationtype_old")
    op.execute("CREATE TYPE obligationtype AS ENUM ('VAT201', 'EMP201', 'ITR14', 'ITR12', 'IRP6')")
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN obligation_type "
        "TYPE obligationtype USING obligation_type::text::obligationtype"
    )
    op.execute("DROP TYPE obligationtype_old")
