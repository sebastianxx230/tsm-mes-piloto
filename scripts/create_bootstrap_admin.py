"""Create the first V2 administrator without embedding credentials in SQL."""

from getpass import getpass
from pathlib import Path
import re
import sys

from werkzeug.security import generate_password_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app  # noqa: E402
from db_config import db  # noqa: E402
from models.usuario import RolSistema, Usuario  # noqa: E402


USERNAME_PATTERN = re.compile(r'^[a-z0-9._-]{3,50}$')


def main():
    username = input('Usuario inicial: ').strip().lower()
    name = input('Nombre completo: ').strip()
    password = getpass('Contraseña (mínimo 12 caracteres): ')
    confirmation = getpass('Confirmar contraseña: ')
    if not USERNAME_PATTERN.fullmatch(username):
        raise SystemExit('Usuario inválido.')
    if not name or len(name) > 100:
        raise SystemExit('Nombre inválido.')
    if len(password) < 12 or password != confirmation:
        raise SystemExit('La contraseña no cumple el mínimo o no coincide.')

    with app.app_context():
        if Usuario.query.filter_by(username=username).first():
            raise SystemExit('Ese usuario ya existe.')
        roles = RolSistema.query.filter(RolSistema.clave.in_((
            'administrador_sistema',
            'produccion_oficina',
        ))).all()
        if len(roles) != 2:
            raise SystemExit('El catálogo RBAC no está preparado.')
        user = Usuario(
            username=username,
            nombre=name,
            password_hash=generate_password_hash(password),
            rol='editor',
            activo=True,
            roles=roles,
        )
        db.session.add(user)
        db.session.commit()
        print('Cuenta inicial creada con Administración del sistema y Producción Oficina.')


if __name__ == '__main__':
    main()
