"""ensure dashboard scale indexes (H3 chunk 3)

Revision ID: a7c4e1f2b9d3
Revises: f3a92b8c4d10
Create Date: 2026-06-12 07:30:00.000000

The dashboard filters open statuses and orders by due date, so each instance table wants a
composite (status, due-date) index plus a plain (client_id) index (Postgres does not
auto-index foreign keys). All four already exist from the tables' original migrations
(6bee3e81960c for obligation_instances, 339f270f74bb for cipc_annual_instances), so this
revision is an idempotent GUARD: CREATE INDEX IF NOT EXISTS is a no-op on a correctly
migrated database and only repairs one where an index was somehow dropped. The downgrade
is intentionally empty — these indexes are owned by the earlier revisions, so this guard
must never drop them. CI's Postgres run is the real proof the chain stays valid.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c4e1f2b9d3"
down_revision = "f3a92b8c4d10"
branch_labels = None
depends_on = None

_INDEXES = (
    (
        "ix_obligation_instances_status_submission_due",
        "obligation_instances",
        "status, submission_due_date",
    ),
    ("ix_obligation_instances_client_id", "obligation_instances", "client_id"),
    ("ix_cipc_annual_instances_status_due", "cipc_annual_instances", "status, due_date"),
    ("ix_cipc_annual_instances_client_id", "cipc_annual_instances", "client_id"),
)


def upgrade():
    for name, table, columns in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade():
    # No-op: these indexes belong to the tables' original migrations. This guard revision
    # only ensures their presence and must not drop them on downgrade.
    pass
