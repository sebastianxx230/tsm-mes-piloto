"""Add auditable warehouse movements and supply lookup index.

Revision ID: 20260824_0017
Revises: 20260824_0016
"""

from alembic import op
import sqlalchemy as sa


revision = '20260824_0017'
down_revision = '20260824_0016'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_componentes_ot_categoria_estado',
        'componentes_ot',
        ['categoria', 'estado_suministro'],
    )
    op.create_table(
        'movimientos_almacen',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('componente_id', sa.Integer(), nullable=True),
        sa.Column('packing_list_id', sa.Integer(), nullable=True),
        sa.Column('ot_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(length=100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('cantidad', sa.Numeric(14, 3), nullable=False),
        sa.Column('unidad', sa.String(length=20), nullable=False),
        sa.Column('estado_anterior', sa.String(length=30), nullable=False),
        sa.Column('estado_nuevo', sa.String(length=30), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('usuario_nombre', sa.String(length=100), nullable=True),
        sa.Column(
            'fecha_creacion',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.ForeignKeyConstraint(
            ['componente_id'],
            ['componentes_ot.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['packing_list_id'],
            ['packing_lists.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['ot_id'],
            ['catalogo_ot.item'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['usuario_id'],
            ['usuarios.id'],
            ondelete='SET NULL',
        ),
    )
    op.create_index(
        'ix_movimientos_almacen_ot_fecha',
        'movimientos_almacen',
        ['ot_id', 'fecha_creacion'],
    )
    op.create_index(
        'ix_movimientos_almacen_componente_fecha',
        'movimientos_almacen',
        ['componente_id', 'fecha_creacion'],
    )


def downgrade():
    op.drop_index(
        'ix_movimientos_almacen_componente_fecha',
        table_name='movimientos_almacen',
    )
    op.drop_index(
        'ix_movimientos_almacen_ot_fecha',
        table_name='movimientos_almacen',
    )
    op.drop_table('movimientos_almacen')
    op.drop_index(
        'ix_componentes_ot_categoria_estado',
        table_name='componentes_ot',
    )
