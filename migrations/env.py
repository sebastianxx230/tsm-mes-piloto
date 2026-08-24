from logging.config import fileConfig
import os

from alembic import context
from flask import current_app
from sqlalchemy.engine import make_url


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_db = current_app.extensions['migrate'].db
target_metadata = target_db.metadata


def _migration_url():
    """Ignore committed example URLs and fall back to Flask's active engine."""
    migration_url = (os.environ.get('MIGRATIONS_DATABASE_URL') or '').strip()
    if not migration_url:
        return None
    if migration_url.startswith('postgres://'):
        migration_url = migration_url.replace('postgres://', 'postgresql://', 1)
    try:
        parsed = make_url(migration_url)
    except Exception:
        return None
    if (parsed.host or '').lower() in {
        'host', 'host-pooler', 'hostname', 'localhost.example'
    }:
        return None
    return migration_url


def get_engine_url():
    migration_url = _migration_url()
    if migration_url:
        return migration_url.replace('%', '%%')
    try:
        return target_db.engine.url.render_as_string(hide_password=False).replace('%', '%%')
    except AttributeError:
        return str(target_db.engine.url).replace('%', '%%')


config.set_main_option('sqlalchemy.url', get_engine_url())


def run_migrations_offline():
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    migration_url = _migration_url()
    connectable = (
        target_db.engine
        if not migration_url
        else target_db.engine.execution_options()
    )
    if migration_url:
        from sqlalchemy import create_engine
        connectable = create_engine(migration_url, pool_pre_ping=True)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
