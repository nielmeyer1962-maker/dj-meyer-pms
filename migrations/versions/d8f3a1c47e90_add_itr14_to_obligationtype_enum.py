"""add ITR14 to obligationtype enum

Revision ID: d8f3a1c47e90
Revises: b7d2e4f10a93
Create Date: 2026-06-10 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8f3a1c47e90'
down_revision = 'b7d2e4f10a93'
branch_labels = None
depends_on = None


def upgrade():
    # obligationtype is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block, so step outside Alembic's wrapping transaction.
    # No positional BEFORE/AFTER — ObligationType order carries no meaning. IF NOT
    # EXISTS keeps the migration idempotent if partially applied.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'ITR14'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # ITR14. Any ITR14 rows would block the cast; none are expected at downgrade time
    # (this revision is what introduces them), so we delete them first to keep the
    # downgrade total. This recreate is transactional, so it runs inside Alembic's
    # normal transaction.
    op.execute("DELETE FROM obligation_instances WHERE obligation_type = 'ITR14'")
    op.execute("ALTER TYPE obligationtype RENAME TO obligationtype_old")
    op.execute("CREATE TYPE obligationtype AS ENUM ('VAT201', 'EMP201')")
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN obligation_type "
        "TYPE obligationtype USING obligation_type::text::obligationtype"
    )
    op.execute("DROP TYPE obligationtype_old")
