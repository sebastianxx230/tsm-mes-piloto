"""Add canonical production personnel and real lot periods.

Revision ID: 20260817_0010
Revises: 20260805_0009
"""

from alembic import op
import sqlalchemy as sa


revision = '20260817_0010'
down_revision = '20260805_0009'
branch_labels = None
depends_on = None


PROCESS_COLUMNS = (
    'hab_real',
    'arm_real',
    'sol_real',
    'lim_real',
    'lib_real',
    'gal_real',
    'are_real',
    'pin_real',
)


def upgrade():
    op.add_column(
        'packing_lists',
        sa.Column('fecha_inicio_real', sa.Date(), nullable=True),
    )
    op.add_column(
        'packing_lists',
        sa.Column('fecha_termino_real', sa.Date(), nullable=True),
    )

    op.create_table(
        'personal_produccion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('nombre_clave', sa.String(length=160), nullable=False),
        sa.Column(
            'activo',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
        sa.Column(
            'fecha_creacion',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.Column(
            'fecha_actualizacion',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'nombre_clave',
            name='uq_personal_produccion_nombre_clave',
        ),
    )
    op.create_index(
        'ix_personal_produccion_activo_nombre',
        'personal_produccion',
        ['activo', 'nombre'],
    )

    for column in PROCESS_COLUMNS:
        op.alter_column(
            'componentes_ot',
            column,
            existing_type=sa.Integer(),
            server_default=sa.text('-1'),
            existing_nullable=False,
        )


def downgrade():
    for column in PROCESS_COLUMNS:
        op.alter_column(
            'componentes_ot',
            column,
            existing_type=sa.Integer(),
            server_default=None,
            existing_nullable=False,
        )
    op.drop_index(
        'ix_personal_produccion_activo_nombre',
        table_name='personal_produccion',
    )
    op.drop_table('personal_produccion')
    op.drop_column('packing_lists', 'fecha_termino_real')
    op.drop_column('packing_lists', 'fecha_inicio_real')
