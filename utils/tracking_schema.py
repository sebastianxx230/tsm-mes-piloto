"""Runtime guard for the small tracking-publication storage tables.

Vercel does not provide a release phase for this Flask deployment.  The normal
Alembic migrations remain the source of truth, while this guard safely repairs
the two additive tables needed by the tracking UI when an existing pilot
database was deployed without running ``flask db upgrade``.
"""

from threading import Lock

from flask import current_app
from sqlalchemy import inspect, text

from db_config import db
from models.catalogo_ot import CatalogoOT  # noqa: F401 - resolves FK metadata
from models.documento_seguimiento import DocumentoSeguimiento
from models.produccion import FotoSeguimiento
from models.usuario import Usuario  # noqa: F401 - resolves FK metadata


POSTGRES_ADVISORY_LOCK_ID = 724_026_817
TRACKING_TABLES = (
    FotoSeguimiento.__table__,
    DocumentoSeguimiento.__table__,
)

_schema_lock = Lock()
_ready_engine_id = None


class TrackingSchemaError(RuntimeError):
    """Raised when the tracking storage cannot be inspected or repaired."""


def _validate_tracking_columns(connection):
    inspector = inspect(connection)
    missing = {}
    for table in TRACKING_TABLES:
        available = {
            column['name']
            for column in inspector.get_columns(table.name)
        }
        expected = {column.name for column in table.columns}
        absent = sorted(expected - available)
        if absent:
            missing[table.name] = absent
    if missing:
        details = '; '.join(
            f'{table}: {", ".join(columns)}'
            for table, columns in missing.items()
        )
        raise TrackingSchemaError(
            f'El esquema de seguimiento tiene columnas pendientes ({details}).'
        )


def ensure_tracking_storage_schema():
    """Create missing tracking tables once per process, without altering data."""
    global _ready_engine_id

    engine = db.engine
    engine_id = id(engine)
    if _ready_engine_id == engine_id:
        return

    with _schema_lock:
        if _ready_engine_id == engine_id:
            return

        created_tables = []
        try:
            with engine.begin() as connection:
                if connection.dialect.name == 'postgresql':
                    connection.execute(
                        text('SELECT pg_advisory_xact_lock(:lock_id)'),
                        {'lock_id': POSTGRES_ADVISORY_LOCK_ID},
                    )

                existing_tables = set(inspect(connection).get_table_names())
                for table in TRACKING_TABLES:
                    if table.name in existing_tables:
                        continue
                    table.create(bind=connection, checkfirst=True)
                    created_tables.append(table.name)

                _validate_tracking_columns(connection)
        except TrackingSchemaError:
            current_app.logger.exception('tracking_schema_validation_failed')
            raise
        except Exception as error:
            current_app.logger.exception(
                'tracking_schema_repair_failed exception_type=%s',
                type(error).__name__,
            )
            raise TrackingSchemaError(
                'No fue posible preparar el almacenamiento de seguimiento.'
            ) from error

        _ready_engine_id = engine_id
        if created_tables:
            current_app.logger.warning(
                'tracking_schema_repaired created_tables=%s',
                ','.join(created_tables),
            )


def reset_tracking_schema_state():
    """Clear the process cache for migrations/tests that replace the schema."""
    global _ready_engine_id
    with _schema_lock:
        _ready_engine_id = None
