"""Runtime guard for additive production-pilot schema changes.

Alembic remains the source of truth. Vercel has no release phase in this Flask
deployment, so the guard creates the personnel table and nullable period
columns when a production request reaches an older pilot database.
"""

from threading import Lock

from flask import current_app
from sqlalchemy import inspect, text

from db_config import db
from models.produccion import PackingList, PersonalProduccion


POSTGRES_ADVISORY_LOCK_ID = 725_026_817
PACKING_LIST_DATE_COLUMNS = {
    'fecha_inicio_real': 'DATE',
    'fecha_termino_real': 'DATE',
}

_schema_lock = Lock()
_ready_engine_id = None


class ProductionSchemaError(RuntimeError):
    """Raised when the production storage cannot be inspected or repaired."""


def _validate_schema(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if PersonalProduccion.__tablename__ not in tables:
        raise ProductionSchemaError(
            'El padrón de personal todavía no está disponible.'
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


def ensure_production_storage_schema():
    """Repair the additive pilot schema once per worker process."""
    global _ready_engine_id

    engine = db.engine
    engine_id = id(engine)
    if _ready_engine_id == engine_id:
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
