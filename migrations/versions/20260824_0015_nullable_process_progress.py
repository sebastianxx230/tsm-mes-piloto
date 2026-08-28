"""Separate unregistered progress from non-applicable processes.

Revision ID: 20260824_0015
Revises: 20260824_0014
"""

from alembic import op
import sqlalchemy as sa


revision = '20260824_0015'
down_revision = '20260824_0014'
branch_labels = None
depends_on = None


PROCESS_COLUMNS = ('hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'are', 'pin')


def upgrade():
    for code in PROCESS_COLUMNS:
        op.drop_constraint(
            f'ck_componentes_ot_{code}_range',
            'componentes_ot',
            type_='check',
        )
        op.alter_column(
            'componentes_ot',
            f'{code}_real',
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
        op.execute(sa.text(
            f'UPDATE componentes_ot SET {code}_real = NULL '
            f'WHERE {code}_real = -1'
        ))
        op.create_check_constraint(
            f'ck_componentes_ot_{code}_range',
            'componentes_ot',
            f'{code}_real IS NULL OR '
            f'({code}_real >= 0 AND {code}_real <= cantidad)',
        )

    op.drop_constraint(
        'ck_avance_elemento_cantidad',
        'avance_elemento_proceso',
        type_='check',
    )
    op.alter_column(
        'avance_elemento_proceso',
        'cantidad_completada',
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    op.execute(sa.text(
        'UPDATE avance_elemento_proceso SET cantidad_completada = NULL '
        'WHERE aplica = false'
    ))
    op.create_check_constraint(
        'ck_avance_elemento_cantidad',
        'avance_elemento_proceso',
        'cantidad_completada IS NULL OR cantidad_completada >= 0',
    )


def downgrade():
    op.drop_constraint(
        'ck_avance_elemento_cantidad',
        'avance_elemento_proceso',
        type_='check',
    )
    op.execute(sa.text(
        'UPDATE avance_elemento_proceso SET cantidad_completada = 0 '
        'WHERE cantidad_completada IS NULL'
    ))
    op.alter_column(
        'avance_elemento_proceso',
        'cantidad_completada',
        existing_type=sa.Integer(),
        nullable=False,
        server_default='0',
    )
    op.create_check_constraint(
        'ck_avance_elemento_cantidad',
        'avance_elemento_proceso',
        'cantidad_completada >= 0',
    )

    for code in PROCESS_COLUMNS:
        op.drop_constraint(
            f'ck_componentes_ot_{code}_range',
            'componentes_ot',
            type_='check',
        )
        op.execute(sa.text(
            f'UPDATE componentes_ot SET {code}_real = -1 '
            f'WHERE {code}_real IS NULL'
        ))
        op.alter_column(
            'componentes_ot',
            f'{code}_real',
            existing_type=sa.Integer(),
            nullable=False,
            server_default='-1',
        )
        op.create_check_constraint(
            f'ck_componentes_ot_{code}_range',
            'componentes_ot',
            f'{code}_real >= -1 AND {code}_real <= cantidad',
        )
