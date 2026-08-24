"""Store a real start and end date for every production element.

Revision ID: 20260824_0016
Revises: 20260824_0015
"""

from alembic import op
import sqlalchemy as sa


revision = '20260824_0016'
down_revision = '20260824_0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'componentes_ot',
        sa.Column('fecha_inicio_real', sa.Date(), nullable=True),
    )
    op.add_column(
        'componentes_ot',
        sa.Column('fecha_termino_real', sa.Date(), nullable=True),
    )
    op.execute(sa.text(
        'UPDATE componentes_ot SET fecha_termino_real = fecha_realizacion '
        'WHERE fecha_realizacion IS NOT NULL'
    ))
    op.create_check_constraint(
        'ck_componentes_ot_periodo_real',
        'componentes_ot',
        'fecha_inicio_real IS NULL OR fecha_termino_real IS NULL OR '
        'fecha_termino_real >= fecha_inicio_real',
    )
    op.create_index(
        'ix_componentes_ot_periodo_real',
        'componentes_ot',
        ['fecha_inicio_real', 'fecha_termino_real'],
    )


def downgrade():
    op.drop_index(
        'ix_componentes_ot_periodo_real',
        table_name='componentes_ot',
    )
    op.drop_constraint(
        'ck_componentes_ot_periodo_real',
        'componentes_ot',
        type_='check',
    )
    op.drop_column('componentes_ot', 'fecha_termino_real')
    op.drop_column('componentes_ot', 'fecha_inicio_real')
