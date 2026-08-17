from sqlalchemy import inspect

from db_config import db
from models.documento_seguimiento import DocumentoSeguimiento
from models.produccion import FotoSeguimiento
from utils.tracking_schema import (
    ensure_tracking_storage_schema,
    reset_tracking_schema_state,
)


def test_runtime_guard_repairs_missing_tracking_tables(
    app,
    client,
    login,
    ids,
):
    with app.app_context():
        db.session.remove()
        DocumentoSeguimiento.__table__.drop(bind=db.engine, checkfirst=True)
        FotoSeguimiento.__table__.drop(bind=db.engine, checkfirst=True)
        reset_tracking_schema_state()

    login('admin')
    assert client.get(f'/api/seguimiento/{ids["ot"]}').status_code == 200
    assert client.get(
        f'/api/seguimiento/{ids["ot"]}/documentos'
    ).status_code == 200

    with app.app_context():
        ensure_tracking_storage_schema()
        table_names = set(inspect(db.engine).get_table_names())
        assert 'documentos_seguimiento' in table_names
        assert 'fotos_seguimiento' in table_names
