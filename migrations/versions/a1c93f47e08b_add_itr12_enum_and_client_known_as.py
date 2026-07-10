"""add ITR12 to obligationtype enum and known_as to clients

Revision ID: a1c93f47e08b
Revises: d8f3a1c47e90
Create Date: 2026-06-11 08:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c93f47e08b'
down_revision = 'd8f3a1c47e90'
branch_labels = None
depends_on = None


def upgrade():
    # known_as is a transactional column add; do it before the enum step (entering an
    # autocommit_block commits the surrounding transaction).
    op.add_column('clients', sa.Column('known_as', sa.String(length=100), nullable=True))

    # obligationtype is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block, so step outside Alembic's wrapping transaction. No
    # positional BEFORE/AFTER — ObligationType order carries no meaning. IF NOT EXISTS
    # keeps the migration idempotent if partially applied. ITR12 is file-only (absent
    # from _PAYMENT_LEG_TYPES), so no model/data change beyond the enum value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'ITR12'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # ITR12. Any ITR12 rows would block the cast; none are expected at downgrade time
    # (this revision is what introduces them), so we delete them first to keep the
    # downgrade total. This recreate is transactional, so it runs inside Alembic's
    # normal transaction. Reverse the enum first, then drop the column.
    op.execute("DELETE FROM obligation_instances WHERE obligation_type = 'ITR12'")
    op.execute("ALTER TYPE obligationtype RENAME TO obligationtype_old")
    op.execute("CREATE TYPE obligationtype AS ENUM ('VAT201', 'EMP201', 'ITR14')")
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN obligation_type "
        "TYPE obligationtype USING obligation_type::text::obligationtype"
    )
    op.execute("DROP TYPE obligationtype_old")

    op.drop_column('clients', 'known_as')
