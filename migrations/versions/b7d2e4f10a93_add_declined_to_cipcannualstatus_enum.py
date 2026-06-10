"""add DECLINED to cipcannualstatus enum

Revision ID: b7d2e4f10a93
Revises: 7c1e0a9b4f23
Create Date: 2026-06-10 05:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d2e4f10a93'
down_revision = '7c1e0a9b4f23'
branch_labels = None
depends_on = None


def upgrade():
    # cipcannualstatus is a NATIVE Postgres enum. ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block, so step outside Alembic's wrapping transaction.
    # DECLINED is a terminal off-ramp appended after CLOSED. IF NOT EXISTS keeps the
    # migration idempotent if partially applied.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE cipcannualstatus ADD VALUE IF NOT EXISTS 'DECLINED' AFTER 'CLOSED'"
        )


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # DECLINED. Any DECLINED rows fall back to GENERATED — the earliest pre-filing state,
    # from which the cycle can be re-driven; there is no single natural predecessor since
    # DECLINED is reachable from four states. This recreate is transactional (only ADD
    # VALUE needs autocommit), so it runs inside Alembic's normal transaction.
    op.execute("ALTER TYPE cipcannualstatus RENAME TO cipcannualstatus_old")
    op.execute(
        "CREATE TYPE cipcannualstatus AS ENUM ("
        "'GENERATED', 'INVOICED', 'INVOICE_PAID', 'BO_SUBMITTED', 'AR_SUBMITTED', 'CLOSED')"
    )
    op.execute(
        "ALTER TABLE cipc_annual_instances ALTER COLUMN status TYPE cipcannualstatus "
        "USING (CASE WHEN status::text = 'DECLINED' THEN 'GENERATED' "
        "ELSE status::text END)::cipcannualstatus"
    )
    op.execute("DROP TYPE cipcannualstatus_old")
