"""add INC to entitytype enum

Revision ID: 4bdfb0e9e6a2
Revises: 339f270f74bb
Create Date: 2026-06-09 13:11:58.751989

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4bdfb0e9e6a2'
down_revision = '339f270f74bb'
branch_labels = None
depends_on = None


def upgrade():
    # entitytype is a NATIVE Postgres enum storing the member NAME. ALTER TYPE ... ADD
    # VALUE cannot run inside a transaction block, so step outside Alembic's wrapping
    # transaction. INC (incorporated company) files a CIPC Annual Return like a Pty Ltd,
    # so position it after PTY_LTD. IF NOT EXISTS keeps the migration idempotent.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE entitytype ADD VALUE IF NOT EXISTS 'INC' AFTER 'PTY_LTD'")


def downgrade():
    # Postgres cannot drop a value from an enum in place, so recreate the type without
    # INC. Any rows still using INC would block the cast; this revision is what
    # introduces INC, so none are expected — guard anyway by leaving such rows to fail
    # loudly rather than silently remapping an entity's legal type.
    op.execute("ALTER TYPE entitytype RENAME TO entitytype_old")
    op.execute(
        "CREATE TYPE entitytype AS ENUM "
        "('INDIVIDUAL', 'SOLE_PROP', 'PTY_LTD', 'CC', 'TRUST', 'PARTNERSHIP', 'NPC')"
    )
    op.execute(
        "ALTER TABLE clients ALTER COLUMN entity_type "
        "TYPE entitytype USING entity_type::text::entitytype"
    )
    op.execute("DROP TYPE entitytype_old")
