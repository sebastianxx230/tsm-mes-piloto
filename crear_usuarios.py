from flask_migrate import upgrade

from app import app


def setup_db():
    with app.app_context():
        upgrade()
        print('Migraciones aplicadas correctamente.')


if __name__ == '__main__':
    setup_db()
