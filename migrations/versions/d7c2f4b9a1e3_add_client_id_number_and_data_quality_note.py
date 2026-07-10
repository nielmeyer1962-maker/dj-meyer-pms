"""add Client.id_number and Client.data_quality_note

Revision ID: d7c2f4b9a1e3
Revises: c5f1a9d2e7b8
Create Date: 2026-07-10 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7c2f4b9a1e3"
down_revision = "c5f1a9d2e7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("id_number", sa.String(length=20), nullable=True))
    op.add_column("clients", sa.Column("data_quality_note", sa.Text(), nullable=True))
    op.create_index(op.f("ix_clients_id_number"), "clients", ["id_number"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_clients_id_number"), table_name="clients")
    op.drop_column("clients", "data_quality_note")
    op.drop_column("clients", "id_number")
