"""Normalize personnel assignments by element process.

Revision ID: 20260828_0018
Revises: 20260824_0017
"""

from alembic import op
import sqlalchemy as sa


revision = '20260828_0018'
down_revision = '20260824_0017'
branch_labels = None
depends_on = None


REPORTING_VIEW_SQL = """
CREATE VIEW vw_ot_personal_produccion AS
SELECT
    ot.item AS ot_id,
    ot.ot,
    ot.cliente,
    ot.fecha_iniciado AS fecha_inicio_ot,
    ot.fecha_termino AS fecha_termino_ot,
    pl.id AS packing_list_id,
    pl.nombre AS packing_list,
    pl.site,
    componente.id AS componente_id,
    componente.marca AS codigo_elemento,
    componente.descripcion AS elemento,
    componente.cantidad AS cantidad_elemento,
    proceso.id AS proceso_id,
    proceso.codigo AS proceso_codigo,
    proceso.nombre AS proceso,
    avance.orden AS orden_proceso,
    avance.aplica,
    avance.cantidad_completada,
    avance.fecha_inicio,
    avance.fecha_fin AS fecha_termino,
    personal.id AS personal_id,
    personal.nombre AS personal,
    personal.activo AS personal_activo,
    asignacion.asignado_por_id,
    asignacion.fecha_creacion AS fecha_asignacion,
    asignacion.fecha_actualizacion
FROM asignaciones_personal_proceso asignacion
JOIN avance_elemento_proceso avance
  ON avance.id = asignacion.avance_id
JOIN personal_produccion personal
  ON personal.id = asignacion.personal_id
JOIN procesos_produccion proceso
  ON proceso.id = avance.proceso_id
JOIN componentes_ot componente
  ON componente.id = avance.componente_id
JOIN packing_lists pl
  ON pl.id = componente.pl_id
JOIN catalogo_ot ot
  ON ot.item = pl.ot_id
WHERE pl.archivado = false
"""


def upgrade():
    op.create_table(
        'asignaciones_personal_proceso',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('avance_id', sa.Integer(), nullable=False),
        sa.Column('personal_id', sa.Integer(), nullable=False),
        sa.Column('asignado_por_id', sa.Integer(), nullable=True),
        sa.Column(
            'fecha_creacion',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'fecha_actualizacion',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.ForeignKeyConstraint(
            ['avance_id'],
            ['avance_elemento_proceso.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['personal_id'],
            ['personal_produccion.id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['asignado_por_id'],
            ['usuarios.id'],
            ondelete='SET NULL',
        ),
        sa.UniqueConstraint(
            'avance_id',
            'personal_id',
            name='uq_asignacion_personal_avance',
        ),
    )
    op.create_index(
        'ix_asignaciones_personal_avance',
        'asignaciones_personal_proceso',
        ['avance_id'],
    )
    op.create_index(
        'ix_asignaciones_personal_personal_avance',
        'asignaciones_personal_proceso',
        ['personal_id', 'avance_id'],
    )
    op.execute(
        'UPDATE catalogo_ot '
        'SET fecha_termino = fecha_iniciado '
        'WHERE fecha_termino IS NULL'
    )
    op.alter_column(
        'catalogo_ot',
        'fecha_termino',
        existing_type=sa.Date(),
        nullable=False,
    )
    op.create_check_constraint(
        'ck_catalogo_ot_periodo_programado',
        'catalogo_ot',
        'fecha_termino >= fecha_iniciado',
    )
    op.execute(REPORTING_VIEW_SQL)


def downgrade():
    op.execute('DROP VIEW IF EXISTS vw_ot_personal_produccion')
    op.drop_constraint(
        'ck_catalogo_ot_periodo_programado',
        'catalogo_ot',
        type_='check',
    )
    op.alter_column(
        'catalogo_ot',
        'fecha_termino',
        existing_type=sa.Date(),
        nullable=True,
    )
    op.drop_index(
        'ix_asignaciones_personal_personal_avance',
        table_name='asignaciones_personal_proceso',
    )
    op.drop_index(
        'ix_asignaciones_personal_avance',
        table_name='asignaciones_personal_proceso',
    )
    op.drop_table('asignaciones_personal_proceso')
