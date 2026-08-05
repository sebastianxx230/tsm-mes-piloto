import os
import tempfile
from datetime import date
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash


TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL')
TEST_DATABASE_PATH = None
if TEST_DATABASE_URL:
    os.environ['DATABASE_URL'] = TEST_DATABASE_URL
else:
    TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f'tsm25-tests-{os.getpid()}.sqlite'
    os.environ['DATABASE_URL'] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ['SECRET_KEY'] = 'test-only-secret-key'

from app import app as flask_app
from db_config import db
from extensions import limiter
from models.catalogo_ot import CatalogoOT
from models.produccion import ComponenteOT, PackingList
from models.usuario import Usuario


@pytest.fixture()
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )
    limiter.reset()

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

        users = [
            Usuario(
                username=role,
                nombre=role.title(),
                rol=role,
                activo=True,
                password_hash=generate_password_hash('valid-password'),
            )
            for role in ('viewer', 'editor', 'admin')
        ]
        db.session.add_all(users)

        work_order = CatalogoOT(
            ot='2026-TEST',
            cliente='Cliente de prueba',
            fecha_iniciado=date(2026, 7, 30),
            descripcion='OT para pruebas de seguridad',
            estado='En Proceso',
        )
        db.session.add(work_order)
        db.session.flush()

        packing_list = PackingList(
            ot_id=work_order.item,
            nombre='PL DE PRUEBA',
            orden=0,
        )
        db.session.add(packing_list)
        db.session.flush()

        component = ComponenteOT(
            pl_id=packing_list.id,
            marca='TEST-001',
            cantidad=10,
            descripcion='Componente de prueba',
            longitud='1000',
            tipo='fabricacion',
            estado_suministro='No requerido',
        )
        db.session.add(component)
        db.session.commit()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
    limiter.reset()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def ids(app):
    with app.app_context():
        return {
            'ot': CatalogoOT.query.filter_by(ot='2026-TEST').one().item,
            'packing_list': PackingList.query.filter_by(nombre='PL DE PRUEBA').one().id,
            'component': ComponenteOT.query.filter_by(marca='TEST-001').one().id,
            'users': {
                role: Usuario.query.filter_by(username=role).one().id
                for role in ('viewer', 'editor', 'admin')
            },
        }


@pytest.fixture()
def login(client, ids):
    def login_as(role):
        with client.session_transaction() as session:
            session['_user_id'] = str(ids['users'][role])
            session['_fresh'] = True
        return client

    return login_as


def pytest_sessionfinish(session, exitstatus):
    if TEST_DATABASE_PATH and TEST_DATABASE_PATH.exists():
        with flask_app.app_context():
            db.session.remove()
            db.engine.dispose()
        try:
            TEST_DATABASE_PATH.unlink()
        except PermissionError:
            # Windows puede retener brevemente un descriptor de SQLite al
            # terminar; no debe convertir una suite correcta en fallo.
            pass
