"""Add an optional manufacturing date to each production element.

Revision ID: 20260817_0011
Revises: 20260817_0010
"""

from alembic import op
import sqlalchemy as sa


revision = '20260817_0011'
down_revision = '20260817_0010'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {
        column['name']
        for column in sa.inspect(connection).get_columns('componentes_ot')
    }
    if 'fecha_realizacion' not in columns:
        op.add_column(
            'componentes_ot',
            sa.Column('fecha_realizacion', sa.Date(), nullable=True),
        )


def downgrade():
    connection = op.get_bind()
    columns = {
        column['name']
        for column in sa.inspect(connection).get_columns('componentes_ot')
    }
    if 'fecha_realizacion' in columns:
        op.drop_column('componentes_ot', 'fecha_realizacion')
