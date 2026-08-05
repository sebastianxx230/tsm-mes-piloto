"""Add pilot integrity fields and constraints.

Revision ID: 20260804_0005
Revises: 20260731_0004
"""

from alembic import op
import sqlalchemy as sa


revision = '20260804_0005'
down_revision = '20260731_0004'
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
    # Normalizar primero los datos existentes para que las restricciones no
    # fallen en Neon al aplicarse.
    op.execute("UPDATE packing_lists SET orden = 0 WHERE orden IS NULL OR orden < 0")
    op.execute("UPDATE packing_lists SET fecha_creacion = NOW() WHERE fecha_creacion IS NULL")

    op.add_column(
        'packing_lists',
        sa.Column(
            'version',
            sa.Integer(),
            server_default=sa.text('1'),
            nullable=False,
        ),
    )
    op.add_column(
        'packing_lists',
        sa.Column(
            'fecha_actualizacion',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
    )

    # Reasignar un orden consecutivo por OT antes de crear la unicidad.
    op.execute(
        """
        WITH ordered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY ot_id
                    ORDER BY orden ASC, id ASC
                ) - 1 AS new_order
            FROM packing_lists
        )
        UPDATE packing_lists AS packing_list
        SET orden = ordered.new_order
        FROM ordered
        WHERE packing_list.id = ordered.id
        """
    )

    op.alter_column(
        'packing_lists',
        'orden',
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text('0'),
    )
    op.alter_column(
        'packing_lists',
        'fecha_creacion',
        existing_type=sa.DateTime(),
        nullable=False,
    )

    op.create_unique_constraint(
        'uq_packing_lists_ot_orden',
        'packing_lists',
        ['ot_id', 'orden'],
    )
    op.create_check_constraint(
        'ck_packing_lists_orden_nonnegative',
        'packing_lists',
        'orden >= 0',
    )
    op.create_check_constraint(
        'ck_packing_lists_version_positive',
        'packing_lists',
        'version >= 1',
    )

    # Convertir NULLs antiguos a valores coherentes antes de reforzar columnas.
    op.execute("UPDATE componentes_ot SET tipo = 'fabricacion' WHERE tipo IS NULL")
    op.execute("UPDATE componentes_ot SET estado_suministro = 'Pendiente' WHERE estado_suministro IS NULL")
    op.execute("UPDATE componentes_ot SET operario = '' WHERE operario IS NULL")
    op.execute("UPDATE componentes_ot SET alerta = FALSE WHERE alerta IS NULL")
    op.execute("UPDATE componentes_ot SET cantidad = 0 WHERE cantidad IS NULL OR cantidad < 0")

    for column in PROCESS_COLUMNS:
        op.execute(
            f"UPDATE componentes_ot SET {column} = 0 WHERE {column} IS NULL"
        )
        op.execute(
            f"UPDATE componentes_ot SET {column} = cantidad "
            f"WHERE {column} > cantidad"
        )
        op.execute(
            f"UPDATE componentes_ot SET {column} = -1 WHERE {column} < -1"
        )

    op.execute("UPDATE componentes_ot SET des_real = 0 WHERE des_real IS NULL OR des_real < 0")
    op.execute("UPDATE componentes_ot SET des_real = cantidad WHERE des_real > cantidad")

    op.alter_column(
        'componentes_ot',
        'tipo',
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        'componentes_ot',
        'estado_suministro',
        existing_type=sa.String(length=30),
        nullable=False,
    )
    op.alter_column(
        'componentes_ot',
        'operario',
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.alter_column(
        'componentes_ot',
        'alerta',
        existing_type=sa.Boolean(),
        nullable=False,
    )

    for column in (*PROCESS_COLUMNS, 'des_real'):
        op.alter_column(
            'componentes_ot',
            column,
            existing_type=sa.Integer(),
            nullable=False,
        )

    op.create_check_constraint(
        'ck_componentes_ot_cantidad_nonnegative',
        'componentes_ot',
        'cantidad >= 0',
    )
    for column in PROCESS_COLUMNS:
        op.create_check_constraint(
            f'ck_componentes_ot_{column.removesuffix("_real")}_range',
            'componentes_ot',
            f'{column} >= -1 AND {column} <= cantidad',
        )
    op.create_check_constraint(
        'ck_componentes_ot_des_range',
        'componentes_ot',
        'des_real >= 0 AND des_real <= cantidad',
    )

    op.execute("UPDATE fotos_seguimiento SET orden = 0 WHERE orden IS NULL OR orden < 0")
    op.execute(
        "UPDATE fotos_seguimiento SET fecha_actualizacion = NOW() "
        "WHERE fecha_actualizacion IS NULL"
    )
    op.alter_column(
        'fotos_seguimiento',
        'fecha_actualizacion',
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.create_check_constraint(
        'ck_fotos_seguimiento_orden_nonnegative',
        'fotos_seguimiento',
        'orden >= 0',
    )


def downgrade():
    op.drop_constraint(
        'ck_fotos_seguimiento_orden_nonnegative',
        'fotos_seguimiento',
        type_='check',
    )
    op.alter_column(
        'fotos_seguimiento',
        'fecha_actualizacion',
        existing_type=sa.DateTime(),
        nullable=True,
    )

    op.drop_constraint(
        'ck_componentes_ot_des_range',
        'componentes_ot',
        type_='check',
    )
    for column in reversed(PROCESS_COLUMNS):
        op.drop_constraint(
            f'ck_componentes_ot_{column.removesuffix("_real")}_range',
            'componentes_ot',
            type_='check',
        )
    op.drop_constraint(
        'ck_componentes_ot_cantidad_nonnegative',
        'componentes_ot',
        type_='check',
    )

    for column in (*PROCESS_COLUMNS, 'des_real'):
        op.alter_column(
            'componentes_ot',
            column,
            existing_type=sa.Integer(),
            nullable=True,
        )
    op.alter_column(
        'componentes_ot',
        'alerta',
        existing_type=sa.Boolean(),
        nullable=True,
    )
    op.alter_column(
        'componentes_ot',
        'operario',
        existing_type=sa.String(length=100),
        nullable=True,
    )
    op.alter_column(
        'componentes_ot',
        'estado_suministro',
        existing_type=sa.String(length=30),
        nullable=True,
    )
    op.alter_column(
        'componentes_ot',
        'tipo',
        existing_type=sa.String(length=20),
        nullable=True,
    )

    op.drop_constraint(
        'ck_packing_lists_version_positive',
        'packing_lists',
        type_='check',
    )
    op.drop_constraint(
        'ck_packing_lists_orden_nonnegative',
        'packing_lists',
        type_='check',
    )
    op.drop_constraint(
        'uq_packing_lists_ot_orden',
        'packing_lists',
        type_='unique',
    )
    op.alter_column(
        'packing_lists',
        'fecha_creacion',
        existing_type=sa.DateTime(),
        nullable=True,
    )
    op.alter_column(
        'packing_lists',
        'orden',
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    op.drop_column('packing_lists', 'fecha_actualizacion')
    op.drop_column('packing_lists', 'version')
