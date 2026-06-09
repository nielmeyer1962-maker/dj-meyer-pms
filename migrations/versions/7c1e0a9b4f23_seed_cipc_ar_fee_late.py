"""seed cipc_ar_fees.fee_late (on-time + R150 fixed penalty)

Revision ID: 7c1e0a9b4f23
Revises: 0629a686b680
Create Date: 2026-06-09 17:10:00.000000

Data-only: the cipc_ar_fees rows were seeded with fee_late = NULL by migration
0629a686b680. Niel confirmed (2026-06-09) the late fee is the on-time fee plus a flat
R150 penalty, the same for every turnover band and both entity classes. This back-fills
fee_late on the existing rows; on downgrade it returns them to NULL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1e0a9b4f23'
down_revision = '0629a686b680'
branch_labels = None
depends_on = None


def upgrade():
    # late = on-time + R150 fixed penalty; accepted by Niel 2026-06-09; CIPC fees subject
    # to annual adjustment — re-verify on change. Only touch rows still unset.
    op.execute(
        sa.text(
            "UPDATE cipc_ar_fees SET fee_late = fee_on_time + 150 WHERE fee_late IS NULL"
        )
    )


def downgrade():
    op.execute(sa.text("UPDATE cipc_ar_fees SET fee_late = NULL"))
