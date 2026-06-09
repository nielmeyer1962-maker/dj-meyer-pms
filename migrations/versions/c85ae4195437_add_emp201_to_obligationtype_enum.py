"""add EMP201 to obligationtype enum

Revision ID: c85ae4195437
Revises: 9c5a26ed594e
Create Date: 2026-06-09 09:05:28.207229

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c85ae4195437'
down_revision = '9c5a26ed594e'
branch_labels = None
depends_on = None


def upgrade():
    # obligationtype is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block, so step outside Alembic's wrapping transaction.
    # No positional BEFORE/AFTER — ObligationType order carries no meaning. IF NOT
    # EXISTS keeps the migration idempotent if partially applied.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'EMP201'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # EMP201. Any EMP201 rows would block the cast; none are expected at downgrade time
    # (this revision is what introduces them), so we delete them first to keep the
    # downgrade total. This recreate is transactional, so it runs inside Alembic's
    # normal transaction.
    op.execute("DELETE FROM obligation_instances WHERE obligation_type = 'EMP201'")
    op.execute("ALTER TYPE obligationtype RENAME TO obligationtype_old")
    op.execute("CREATE TYPE obligationtype AS ENUM ('VAT201')")
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN obligation_type "
        "TYPE obligationtype USING obligation_type::text::obligationtype"
    )
    op.execute("DROP TYPE obligationtype_old")
