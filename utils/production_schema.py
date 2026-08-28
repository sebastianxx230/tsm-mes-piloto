"""Runtime guard for additive production-pilot schema changes.

Alembic remains the source of truth. Vercel has no release phase in this Flask
deployment, so the guard creates additive production columns and tables when
a request reaches an older pilot database.
"""

import os
from threading import Lock

from flask import current_app
from sqlalchemy import inspect, text

from db_config import db
from models.produccion import (
    AsignacionPersonalProceso,
    AvanceElementoProceso,
    ComponenteOT,
    ImportacionPackingList,
    MovimientoAlmacen,
    PackingList,
    PersonalProduccion,
    ProcesoProduccion,
    RutaProceso,
    RutaProduccion,
)
from models.usuario import (
    PermisoSistema,
    RolSistema,
    rol_permisos,
    usuario_roles,
)
from utils.rbac_catalog import PERMISSION_SEED, ROLE_SEED


POSTGRES_ADVISORY_LOCK_ID = 725_026_817
PACKING_LIST_DATE_COLUMNS = {
    'fecha_inicio_real': 'DATE',
    'fecha_termino_real': 'DATE',
    'site': 'VARCHAR(150)',
}
COMPONENT_DATE_COLUMNS = {
    'fecha_realizacion': 'DATE',
    'fecha_inicio_real': 'DATE',
    'fecha_termino_real': 'DATE',
    'categoria': "VARCHAR(30) NOT NULL DEFAULT 'FABRICACION'",
    'subcategoria': 'VARCHAR(50)',
    'unidad': "VARCHAR(20) NOT NULL DEFAULT 'UND'",
    'ubicacion': 'VARCHAR(255)',
    'perfil': 'VARCHAR(150)',
    'material': 'VARCHAR(150)',
    'longitud_mm': 'NUMERIC(14,3)',
    'area_unitaria_m2': 'NUMERIC(14,4)',
    'area_total_m2': 'NUMERIC(14,4)',
    'peso_unitario_kg': 'NUMERIC(14,4)',
    'peso_total_kg': 'NUMERIC(14,4)',
    'fila_origen': 'INTEGER',
    'ruta_id': 'INTEGER',
    'importacion_id': 'INTEGER',
}
NULLABLE_COMPONENT_PROGRESS_COLUMNS = (
    'hab_real',
    'arm_real',
    'sol_real',
    'lim_real',
    'lib_real',
    'gal_real',
    'are_real',
    'pin_real',
)

V2_TABLES = (
    ProcesoProduccion,
    RutaProduccion,
    ImportacionPackingList,
    RutaProceso,
    AvanceElementoProceso,
    AsignacionPersonalProceso,
    MovimientoAlmacen,
)

IDENTITY_MODELS = (RolSistema, PermisoSistema)
IDENTITY_TABLES = (usuario_roles, rol_permisos)

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
    ('GALVANIZADO', 'Fabricación galvanizada', (
        'hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'des',
    )),
    ('PINTADO', 'Fabricación pintada', (
        'hab', 'arm', 'sol', 'lim', 'lib', 'are', 'pin', 'des',
    )),
)

_schema_lock = Lock()
_ready_engine_id = None


class ProductionSchemaError(RuntimeError):
    """Raised when the production storage cannot be inspected or repaired."""


def _validate_schema(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    required_tables = {
        PersonalProduccion.__tablename__,
        *(model.__tablename__ for model in V2_TABLES),
        *(model.__tablename__ for model in IDENTITY_MODELS),
        *(table.name for table in IDENTITY_TABLES),
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise ProductionSchemaError(
            'El esquema V2 tiene tablas pendientes: '
            + ', '.join(missing_tables)
        )

    packing_columns = {
        column['name']
        for column in inspector.get_columns(PackingList.__tablename__)
    }
    missing = sorted(set(PACKING_LIST_DATE_COLUMNS) - packing_columns)
    if missing:
        raise ProductionSchemaError(
            'El esquema de lotes tiene fechas pendientes: '
            + ', '.join(missing)
        )

    component_column_map = {
        column['name']: column
        for column in inspector.get_columns(ComponenteOT.__tablename__)
    }
    missing = sorted(set(COMPONENT_DATE_COLUMNS) - set(component_column_map))
    if missing:
        raise ProductionSchemaError(
            'El esquema de elementos tiene fechas pendientes: '
            + ', '.join(missing)
        )

    non_nullable_progress = sorted(
        column_name
        for column_name in NULLABLE_COMPONENT_PROGRESS_COLUMNS
        if not component_column_map[column_name]['nullable']
    )
    process_progress_columns = {
        column['name']: column
        for column in inspector.get_columns(
            AvanceElementoProceso.__tablename__
        )
    }
    if not process_progress_columns['cantidad_completada']['nullable']:
        non_nullable_progress.append(
            'avance_elemento_proceso.cantidad_completada'
        )
    if non_nullable_progress:
        raise ProductionSchemaError(
            'El esquema conserva avances obligatorios incompatibles: '
            + ', '.join(non_nullable_progress)
        )


def _seed_v2_catalog(connection):
    for code, name, order, weight in PROCESS_SEED:
        exists = connection.execute(
            text('SELECT 1 FROM procesos_produccion WHERE codigo = :codigo'),
            {'codigo': code},
        ).scalar()
        if not exists:
            connection.execute(
                text(
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
            text('SELECT id FROM rutas_produccion WHERE codigo = :codigo'),
            {'codigo': route_code},
        ).scalar()
        if route_id is None:
            connection.execute(
                text(
                    'INSERT INTO rutas_produccion '
                    '(codigo, nombre, activo, fecha_creacion, fecha_actualizacion) '
                    'VALUES (:codigo, :nombre, true, CURRENT_TIMESTAMP, '
                    'CURRENT_TIMESTAMP)'
                ),
                {'codigo': route_code, 'nombre': route_name},
            )
            route_id = connection.execute(
                text('SELECT id FROM rutas_produccion WHERE codigo = :codigo'),
                {'codigo': route_code},
            ).scalar_one()

        for order, process_code in enumerate(process_codes):
            process_id = connection.execute(
                text('SELECT id FROM procesos_produccion WHERE codigo = :codigo'),
                {'codigo': process_code},
            ).scalar_one()
            exists = connection.execute(
                text(
                    'SELECT 1 FROM ruta_procesos '
                    'WHERE ruta_id = :ruta_id AND proceso_id = :proceso_id'
                ),
                {'ruta_id': route_id, 'proceso_id': process_id},
            ).scalar()
            if not exists:
                connection.execute(
                    text(
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


def _seed_identity_catalog(connection):
    permission_ids = {}
    for permission_key, permission_name in PERMISSION_SEED:
        permission_id = connection.execute(
            text(
                'SELECT id FROM permisos_sistema WHERE clave = :clave'
            ),
            {'clave': permission_key},
        ).scalar()
        if permission_id is None:
            connection.execute(
                text(
                    'INSERT INTO permisos_sistema (clave, nombre) '
                    'VALUES (:clave, :nombre)'
                ),
                {'clave': permission_key, 'nombre': permission_name},
            )
            permission_id = connection.execute(
                text(
                    'SELECT id FROM permisos_sistema WHERE clave = :clave'
                ),
                {'clave': permission_key},
            ).scalar_one()
        permission_ids[permission_key] = permission_id

    role_ids = {}
    for role_key, role_name, permissions in ROLE_SEED:
        role_id = connection.execute(
            text('SELECT id FROM roles_sistema WHERE clave = :clave'),
            {'clave': role_key},
        ).scalar()
        if role_id is None:
            connection.execute(
                text(
                    'INSERT INTO roles_sistema (clave, nombre, activo) '
                    'VALUES (:clave, :nombre, true)'
                ),
                {'clave': role_key, 'nombre': role_name},
            )
            role_id = connection.execute(
                text('SELECT id FROM roles_sistema WHERE clave = :clave'),
                {'clave': role_key},
            ).scalar_one()
        role_ids[role_key] = role_id
        connection.execute(
            text('DELETE FROM rol_permisos WHERE rol_id = :rol_id'),
            {'rol_id': role_id},
        )
        for permission_key in permissions:
            permission_id = permission_ids[permission_key]
            exists = connection.execute(
                text(
                    'SELECT 1 FROM rol_permisos '
                    'WHERE rol_id = :rol_id AND permiso_id = :permiso_id'
                ),
                {'rol_id': role_id, 'permiso_id': permission_id},
            ).scalar()
            if not exists:
                connection.execute(
                    text(
                        'INSERT INTO rol_permisos (rol_id, permiso_id) '
                        'VALUES (:rol_id, :permiso_id)'
                    ),
                    {'rol_id': role_id, 'permiso_id': permission_id},
                )

    legacy_mapping = {
        'admin': ('administrador_sistema', 'produccion_oficina'),
        'editor': ('produccion_oficina',),
        'viewer': ('produccion_planta',),
    }
    users = connection.execute(text('SELECT id, rol FROM usuarios')).all()
    for user_id, legacy_role in users:
        for role_key in legacy_mapping.get(legacy_role, ()):
            role_id = role_ids[role_key]
            exists = connection.execute(
                text(
                    'SELECT 1 FROM usuario_roles '
                    'WHERE usuario_id = :usuario_id AND rol_id = :rol_id'
                ),
                {'usuario_id': user_id, 'rol_id': role_id},
            ).scalar()
            if not exists:
                connection.execute(
                    text(
                        'INSERT INTO usuario_roles (usuario_id, rol_id) '
                        'VALUES (:usuario_id, :rol_id)'
                    ),
                    {'usuario_id': user_id, 'rol_id': role_id},
                )


def ensure_production_storage_schema():
    """Repair the additive pilot schema once per worker process."""
    global _ready_engine_id

    engine = db.engine
    engine_id = id(engine)
    if _ready_engine_id == engine_id:
        return

    auto_repair_setting = os.environ.get('AUTO_REPAIR_PRODUCTION_SCHEMA')
    if auto_repair_setting is None:
        auto_repair_enabled = not bool(os.environ.get('VERCEL'))
    else:
        auto_repair_enabled = auto_repair_setting.strip().lower() in {
            '1', 'true', 'yes', 'on',
        }
    if not auto_repair_enabled:
        _ready_engine_id = engine_id
        return

    with _schema_lock:
        if _ready_engine_id == engine_id:
            return

        repaired = []
        try:
            with engine.begin() as connection:
                if connection.dialect.name == 'postgresql':
                    connection.execute(
                        text('SELECT pg_advisory_xact_lock(:lock_id)'),
                        {'lock_id': POSTGRES_ADVISORY_LOCK_ID},
                    )

                inspector = inspect(connection)
                tables = set(inspector.get_table_names())
                if PersonalProduccion.__tablename__ not in tables:
                    PersonalProduccion.__table__.create(
                        bind=connection,
                        checkfirst=True,
                    )
                    repaired.append(PersonalProduccion.__tablename__)

                for model in IDENTITY_MODELS:
                    if model.__tablename__ in tables:
                        continue
                    model.__table__.create(bind=connection, checkfirst=True)
                    tables.add(model.__tablename__)
                    repaired.append(model.__tablename__)

                for table in IDENTITY_TABLES:
                    if table.name in tables:
                        continue
                    table.create(bind=connection, checkfirst=True)
                    tables.add(table.name)
                    repaired.append(table.name)

                for model in V2_TABLES:
                    if model.__tablename__ in tables:
                        continue
                    model.__table__.create(bind=connection, checkfirst=True)
                    tables.add(model.__tablename__)
                    repaired.append(model.__tablename__)

                packing_columns = {
                    column['name']
                    for column in inspect(connection).get_columns(
                        PackingList.__tablename__
                    )
                }
                for column_name, sql_type in PACKING_LIST_DATE_COLUMNS.items():
                    if column_name in packing_columns:
                        continue
                    connection.execute(text(
                        f'ALTER TABLE {PackingList.__tablename__} '
                        f'ADD COLUMN {column_name} {sql_type}'
                    ))
                    repaired.append(
                        f'{PackingList.__tablename__}.{column_name}'
                    )

                component_columns = {
                    column['name']
                    for column in inspect(connection).get_columns(
                        ComponenteOT.__tablename__
                    )
                }
                for column_name, sql_type in COMPONENT_DATE_COLUMNS.items():
                    if column_name in component_columns:
                        continue
                    connection.execute(text(
                        f'ALTER TABLE {ComponenteOT.__tablename__} '
                        f'ADD COLUMN {column_name} {sql_type}'
                    ))
                    repaired.append(
                        f'{ComponenteOT.__tablename__}.{column_name}'
                    )

                if connection.dialect.name == 'postgresql':
                    component_column_map = {
                        column['name']: column
                        for column in inspect(connection).get_columns(
                            ComponenteOT.__tablename__
                        )
                    }
                    for column_name in NULLABLE_COMPONENT_PROGRESS_COLUMNS:
                        column = component_column_map.get(column_name)
                        if column is None or column['nullable']:
                            continue
                        connection.execute(text(
                            f'ALTER TABLE {ComponenteOT.__tablename__} '
                            f'ALTER COLUMN {column_name} DROP NOT NULL'
                        ))
                        connection.execute(text(
                            f'ALTER TABLE {ComponenteOT.__tablename__} '
                            f'ALTER COLUMN {column_name} DROP DEFAULT'
                        ))
                        repaired.append(
                            f'{ComponenteOT.__tablename__}.{column_name}:nullable'
                        )

                    process_progress_columns = {
                        column['name']: column
                        for column in inspect(connection).get_columns(
                            AvanceElementoProceso.__tablename__
                        )
                    }
                    completed_column = process_progress_columns.get(
                        'cantidad_completada'
                    )
                    if completed_column and not completed_column['nullable']:
                        connection.execute(text(
                            'ALTER TABLE avance_elemento_proceso '
                            'ALTER COLUMN cantidad_completada DROP NOT NULL'
                        ))
                        connection.execute(text(
                            'ALTER TABLE avance_elemento_proceso '
                            'ALTER COLUMN cantidad_completada DROP DEFAULT'
                        ))
                        repaired.append(
                            'avance_elemento_proceso.cantidad_completada:nullable'
                        )

                # Las filas V1 ya existentes conservan su clasificación al
                # incorporar la columna. El DEFAULT solo cubre fabricación.
                connection.execute(text(
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

                _seed_v2_catalog(connection)
                _seed_identity_catalog(connection)

                _validate_schema(connection)
        except ProductionSchemaError:
            current_app.logger.exception('production_schema_validation_failed')
            raise
        except Exception as error:
            current_app.logger.exception(
                'production_schema_repair_failed exception_type=%s',
                type(error).__name__,
            )
            raise ProductionSchemaError(
                'No fue posible preparar el almacenamiento de producción.'
            ) from error

        _ready_engine_id = engine_id
        if repaired:
            current_app.logger.warning(
                'production_schema_repaired items=%s',
                ','.join(repaired),
            )


def reset_production_schema_state():
    """Clear the process cache for tests that replace the database schema."""
    global _ready_engine_id
    with _schema_lock:
        _ready_engine_id = None
