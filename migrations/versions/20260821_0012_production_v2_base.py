"""Add normalized production V2 base and rich packing-list items.

Revision ID: 20260821_0012
Revises: 20260817_0011
"""

from alembic import op
import sqlalchemy as sa


revision = '20260821_0012'
down_revision = '20260817_0011'
branch_labels = None
depends_on = None


PROCESS_SEED = (
    ('hab', 'Habilitado', 0, 12),
    ('arm', 'Armado', 1, 24),
    ('sol', 'Soldadura', 2, 28),
    ('lim', 'Limpieza', 3, 12),
    ('lib', 'Liberación', 4, 6),
    ('gal', 'Galvanizado', 5, 6),
    ('are', 'Arenado', 6, 6),
    ('pin', 'Pintado', 7, 6),
    ('des', 'Despacho', 8, 0),
)

ROUTE_SEED = (
    (
        'GALVANIZADO',
        'Fabricación galvanizada',
        ('hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'des'),
    ),
    (
        'PINTADO',
        'Fabricación pintada',
        ('hab', 'arm', 'sol', 'lim', 'lib', 'are', 'pin', 'des'),
    ),
)


def _table_names(connection):
    return set(sa.inspect(connection).get_table_names())


def _columns(connection, table_name):
    return {
        column['name']
        for column in sa.inspect(connection).get_columns(table_name)
    }


def _indexes(connection, table_name):
    return {
        index['name']
        for index in sa.inspect(connection).get_indexes(table_name)
    }


def _foreign_keys(connection, table_name):
    return {
        foreign_key['name']
        for foreign_key in sa.inspect(connection).get_foreign_keys(table_name)
        if foreign_key.get('name')
    }


def _seed_catalog(connection):
    for code, name, order, weight in PROCESS_SEED:
        exists = connection.execute(
            sa.text(
                'SELECT 1 FROM procesos_produccion WHERE codigo = :codigo'
            ),
            {'codigo': code},
        ).scalar()
        if not exists:
            connection.execute(
                sa.text(
                    'INSERT INTO procesos_produccion '
                    '(codigo, nombre, orden, peso_default, controla_cantidad, '
                    'activo, fecha_creacion, fecha_actualizacion) '
                    'VALUES (:codigo, :nombre, :orden, :peso, true, true, '
                    'CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
                ),
                {
                    'codigo': code,
                    'nombre': name,
                    'orden': order,
                    'peso': weight,
                },
            )

    for route_code, route_name, process_codes in ROUTE_SEED:
        route_id = connection.execute(
            sa.text(
                'SELECT id FROM rutas_produccion WHERE codigo = :codigo'
            ),
            {'codigo': route_code},
        ).scalar()
        if route_id is None:
            connection.execute(
                sa.text(
                    'INSERT INTO rutas_produccion '
                    '(codigo, nombre, activo, fecha_creacion, fecha_actualizacion) '
                    'VALUES (:codigo, :nombre, true, CURRENT_TIMESTAMP, '
                    'CURRENT_TIMESTAMP)'
                ),
                {'codigo': route_code, 'nombre': route_name},
            )
            route_id = connection.execute(
                sa.text(
                    'SELECT id FROM rutas_produccion WHERE codigo = :codigo'
                ),
                {'codigo': route_code},
            ).scalar_one()

        for order, process_code in enumerate(process_codes):
            process_id = connection.execute(
                sa.text(
                    'SELECT id FROM procesos_produccion WHERE codigo = :codigo'
                ),
                {'codigo': process_code},
            ).scalar_one()
            exists = connection.execute(
                sa.text(
                    'SELECT 1 FROM ruta_procesos '
                    'WHERE ruta_id = :ruta_id AND proceso_id = :proceso_id'
                ),
                {'ruta_id': route_id, 'proceso_id': process_id},
            ).scalar()
            if not exists:
                connection.execute(
                    sa.text(
                        'INSERT INTO ruta_procesos '
                        '(ruta_id, proceso_id, orden, obligatorio, peso) '
                        'VALUES (:ruta_id, :proceso_id, :orden, true, NULL)'
                    ),
                    {
                        'ruta_id': route_id,
                        'proceso_id': process_id,
                        'orden': order,
                    },
                )


def upgrade():
    connection = op.get_bind()
    tables = _table_names(connection)

    if 'procesos_produccion' not in tables:
        op.create_table(
            'procesos_produccion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('codigo', sa.String(length=20), nullable=False),
            sa.Column('nombre', sa.String(length=80), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('orden', sa.Integer(), server_default='0', nullable=False),
            sa.Column(
                'peso_default',
                sa.Numeric(precision=5, scale=2),
                server_default='0',
                nullable=False,
            ),
            sa.Column(
                'controla_cantidad',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
            sa.Column(
                'activo',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
            sa.Column(
                'fecha_creacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.Column(
                'fecha_actualizacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.CheckConstraint('orden >= 0', name='ck_procesos_produccion_orden'),
            sa.CheckConstraint(
                'peso_default >= 0 AND peso_default <= 100',
                name='ck_procesos_produccion_peso',
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('codigo'),
        )
        op.create_index(
            'ix_procesos_produccion_activo_orden',
            'procesos_produccion',
            ['activo', 'orden'],
        )

    tables = _table_names(connection)
    if 'rutas_produccion' not in tables:
        op.create_table(
            'rutas_produccion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('codigo', sa.String(length=40), nullable=False),
            sa.Column('nombre', sa.String(length=100), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column(
                'activo',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
            sa.Column(
                'fecha_creacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.Column(
                'fecha_actualizacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('codigo'),
        )
        op.create_index(
            'ix_rutas_produccion_activo_nombre',
            'rutas_produccion',
            ['activo', 'nombre'],
        )

    tables = _table_names(connection)
    if 'ruta_procesos' not in tables:
        op.create_table(
            'ruta_procesos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('ruta_id', sa.Integer(), nullable=False),
            sa.Column('proceso_id', sa.Integer(), nullable=False),
            sa.Column('orden', sa.Integer(), nullable=False),
            sa.Column(
                'obligatorio',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
            sa.Column(
                'peso',
                sa.Numeric(precision=5, scale=2),
                nullable=True,
            ),
            sa.CheckConstraint('orden >= 0', name='ck_ruta_procesos_orden'),
            sa.CheckConstraint(
                'peso IS NULL OR (peso >= 0 AND peso <= 100)',
                name='ck_ruta_procesos_peso',
            ),
            sa.ForeignKeyConstraint(
                ['proceso_id'],
                ['procesos_produccion.id'],
                name='fk_ruta_procesos_proceso_id',
                ondelete='RESTRICT',
            ),
            sa.ForeignKeyConstraint(
                ['ruta_id'],
                ['rutas_produccion.id'],
                name='fk_ruta_procesos_ruta_id',
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'ruta_id',
                'proceso_id',
                name='uq_ruta_procesos_ruta_proceso',
            ),
            sa.UniqueConstraint(
                'ruta_id', 'orden', name='uq_ruta_procesos_orden'
            ),
        )

    tables = _table_names(connection)
    if 'importaciones_packing_list' not in tables:
        op.create_table(
            'importaciones_packing_list',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('pl_id', sa.Integer(), nullable=False),
            sa.Column('archivo', sa.String(length=255), nullable=True),
            sa.Column('hoja', sa.String(length=100), nullable=True),
            sa.Column('ot_detectada', sa.String(length=50), nullable=True),
            sa.Column('cantidad_items', sa.Integer(), nullable=False),
            sa.Column(
                'advertencias',
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            ),
            sa.Column('creado_por_id', sa.Integer(), nullable=True),
            sa.Column(
                'fecha_creacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ['creado_por_id'],
                ['usuarios.id'],
                name='fk_importaciones_packing_list_usuario',
                ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['pl_id'],
                ['packing_lists.id'],
                name='fk_importaciones_packing_list_pl',
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_importaciones_packing_list_pl_fecha',
            'importaciones_packing_list',
            ['pl_id', 'fecha_creacion'],
        )

    packing_columns = _columns(connection, 'packing_lists')
    if 'site' not in packing_columns:
        op.add_column(
            'packing_lists',
            sa.Column('site', sa.String(length=150), nullable=True),
        )

    component_columns = _columns(connection, 'componentes_ot')
    component_additions = (
        sa.Column(
            'categoria',
            sa.String(length=30),
            server_default='FABRICACION',
            nullable=False,
        ),
        sa.Column('subcategoria', sa.String(length=50), nullable=True),
        sa.Column(
            'unidad',
            sa.String(length=20),
            server_default='UND',
            nullable=False,
        ),
        sa.Column('ubicacion', sa.String(length=255), nullable=True),
        sa.Column('perfil', sa.String(length=150), nullable=True),
        sa.Column('material', sa.String(length=150), nullable=True),
        sa.Column('longitud_mm', sa.Numeric(14, 3), nullable=True),
        sa.Column('area_unitaria_m2', sa.Numeric(14, 4), nullable=True),
        sa.Column('area_total_m2', sa.Numeric(14, 4), nullable=True),
        sa.Column('peso_unitario_kg', sa.Numeric(14, 4), nullable=True),
        sa.Column('peso_total_kg', sa.Numeric(14, 4), nullable=True),
        sa.Column('fila_origen', sa.Integer(), nullable=True),
        sa.Column('ruta_id', sa.Integer(), nullable=True),
        sa.Column('importacion_id', sa.Integer(), nullable=True),
    )
    for column in component_additions:
        if column.name not in component_columns:
            op.add_column('componentes_ot', column)

    # Conserva la clasificación funcional de los registros creados por V1.
    connection.execute(sa.text(
        "UPDATE componentes_ot SET categoria = CASE "
        "WHEN LOWER(COALESCE(tipo, '')) IN "
        "('p_template', 'p_torre', 'perneria') THEN 'PERNERIA' "
        "WHEN LOWER(COALESCE(tipo, '')) IN "
        "('c_vida', 'vientos', 'suministro') THEN 'SUMINISTRO' "
        "WHEN LOWER(COALESCE(tipo, '')) IN "
        "('fab', 'fabricacion') THEN 'FABRICACION' "
        "ELSE 'OTRO' END "
        "WHERE categoria IS NULL OR "
        "(categoria = 'FABRICACION' AND "
        "LOWER(COALESCE(tipo, '')) NOT IN ('fab', 'fabricacion'))"
    ))

    foreign_keys = _foreign_keys(connection, 'componentes_ot')
    if 'fk_componentes_ot_ruta_id' not in foreign_keys:
        op.create_foreign_key(
            'fk_componentes_ot_ruta_id',
            'componentes_ot',
            'rutas_produccion',
            ['ruta_id'],
            ['id'],
            ondelete='SET NULL',
        )
    if 'fk_componentes_ot_importacion_id' not in foreign_keys:
        op.create_foreign_key(
            'fk_componentes_ot_importacion_id',
            'componentes_ot',
            'importaciones_packing_list',
            ['importacion_id'],
            ['id'],
            ondelete='SET NULL',
        )

    tables = _table_names(connection)
    if 'avance_elemento_proceso' not in tables:
        op.create_table(
            'avance_elemento_proceso',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('componente_id', sa.Integer(), nullable=False),
            sa.Column('proceso_id', sa.Integer(), nullable=False),
            sa.Column('orden', sa.Integer(), nullable=False),
            sa.Column(
                'aplica',
                sa.Boolean(),
                server_default=sa.text('false'),
                nullable=False,
            ),
            sa.Column(
                'cantidad_completada',
                sa.Integer(),
                server_default='0',
                nullable=False,
            ),
            sa.Column('fecha_inicio', sa.Date(), nullable=True),
            sa.Column('fecha_fin', sa.Date(), nullable=True),
            sa.Column('actualizado_por_id', sa.Integer(), nullable=True),
            sa.Column(
                'fecha_actualizacion',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            ),
            sa.CheckConstraint('orden >= 0', name='ck_avance_elemento_orden'),
            sa.CheckConstraint(
                'cantidad_completada >= 0',
                name='ck_avance_elemento_cantidad',
            ),
            sa.ForeignKeyConstraint(
                ['actualizado_por_id'],
                ['usuarios.id'],
                name='fk_avance_elemento_usuario',
                ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['componente_id'],
                ['componentes_ot.id'],
                name='fk_avance_elemento_componente',
                ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['proceso_id'],
                ['procesos_produccion.id'],
                name='fk_avance_elemento_proceso',
                ondelete='RESTRICT',
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'componente_id',
                'proceso_id',
                name='uq_avance_elemento_proceso',
            ),
        )
        op.create_index(
            'ix_avance_elemento_componente_orden',
            'avance_elemento_proceso',
            ['componente_id', 'orden'],
        )

    _seed_catalog(connection)


def downgrade():
    op.drop_index(
        'ix_avance_elemento_componente_orden',
        table_name='avance_elemento_proceso',
    )
    op.drop_table('avance_elemento_proceso')
    op.drop_constraint(
        'fk_componentes_ot_importacion_id',
        'componentes_ot',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_componentes_ot_ruta_id',
        'componentes_ot',
        type_='foreignkey',
    )
    for column in (
        'importacion_id',
        'ruta_id',
        'fila_origen',
        'peso_total_kg',
        'peso_unitario_kg',
        'area_total_m2',
        'area_unitaria_m2',
        'longitud_mm',
        'material',
        'perfil',
        'ubicacion',
        'unidad',
        'subcategoria',
        'categoria',
    ):
        op.drop_column('componentes_ot', column)
    op.drop_column('packing_lists', 'site')
    op.drop_index(
        'ix_importaciones_packing_list_pl_fecha',
        table_name='importaciones_packing_list',
    )
    op.drop_table('importaciones_packing_list')
    op.drop_table('ruta_procesos')
    op.drop_index(
        'ix_rutas_produccion_activo_nombre',
        table_name='rutas_produccion',
    )
    op.drop_table('rutas_produccion')
    op.drop_index(
        'ix_procesos_produccion_activo_orden',
        table_name='procesos_produccion',
    )
    op.drop_table('procesos_produccion')
