"""add VAT fields to clients table

Revision ID: 6102eb116e8d
Revises: a1d8b9a7c82c
Create Date: 2026-05-12 17:23:55.690164

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '6102eb116e8d'
down_revision = 'a1d8b9a7c82c'
branch_labels = None
depends_on = None


def upgrade():
    vat_category_enum = postgresql.ENUM('A', 'B', 'C', 'D', 'E', name='vatcategory')
    vat_category_enum.create(op.get_bind(), checkfirst=True)
    vat_submission_method_enum = postgresql.ENUM('EFILING', 'MANUAL', name='vatsubmissionmethod')
    vat_submission_method_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'clients',
        sa.Column(
            'vat_category',
            sa.Enum('A', 'B', 'C', 'D', 'E', name='vatcategory', create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        'clients',
        sa.Column(
            'vat_submission_method',
            sa.Enum('EFILING', 'MANUAL', name='vatsubmissionmethod', create_type=False),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column('clients', 'vat_submission_method')
    op.drop_column('clients', 'vat_category')
