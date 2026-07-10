"""add IRP6 to obligationtype enum and window_code to obligation_instances

Revision ID: b3e8d1a6c402
Revises: a7c4e1f2b9d3
Create Date: 2026-06-13 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3e8d1a6c402'
down_revision = 'a7c4e1f2b9d3'
branch_labels = None
depends_on = None


def upgrade():
    # window_code is a transactional column add; do it before the enum step (entering an
    # autocommit_block commits the surrounding transaction). Nullable: only IRP6 rows set
    # it ("01"/"02"/"03"); every other obligation type leaves it NULL.
    op.add_column(
        'obligation_instances', sa.Column('window_code', sa.String(length=2), nullable=True)
    )

    # obligationtype is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run inside
    # a transaction block, so step outside Alembic's wrapping transaction. No positional
    # BEFORE/AFTER — ObligationType order carries no meaning. IF NOT EXISTS keeps the
    # migration idempotent if partially applied. IRP6 is a payment-leg type (already in
    # _PAYMENT_LEG_TYPES), so no further model/data change beyond the enum value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE obligationtype ADD VALUE IF NOT EXISTS 'IRP6'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # IRP6. Any IRP6 rows would block the cast; none are expected at downgrade time (this
    # revision is what introduces them), so we delete them first to keep the downgrade
    # total. This recreate is transactional, so it runs inside Alembic's normal
    # transaction. Reverse the enum first, then drop the column.
    op.execute("DELETE FROM obligation_instances WHERE obligation_type = 'IRP6'")
    op.execute("ALTER TYPE obligationtype RENAME TO obligationtype_old")
    op.execute("CREATE TYPE obligationtype AS ENUM ('VAT201', 'EMP201', 'ITR14', 'ITR12')")
    op.execute(
        "ALTER TABLE obligation_instances ALTER COLUMN obligation_type "
        "TYPE obligationtype USING obligation_type::text::obligationtype"
    )
    op.execute("DROP TYPE obligationtype_old")

    op.drop_column('obligation_instances', 'window_code')
