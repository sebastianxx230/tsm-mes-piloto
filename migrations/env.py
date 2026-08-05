from logging.config import fileConfig
import os

from alembic import context
from flask import current_app


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_db = current_app.extensions['migrate'].db
target_metadata = target_db.metadata


def get_engine_url():
    migration_url = os.environ.get('MIGRATIONS_DATABASE_URL')
    if migration_url:
        if migration_url.startswith('postgres://'):
            migration_url = migration_url.replace('postgres://', 'postgresql://', 1)
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
    migration_url = os.environ.get('MIGRATIONS_DATABASE_URL')
    connectable = (
        target_db.engine
        if not migration_url
        else target_db.engine.execution_options()
    )
    if migration_url:
        from sqlalchemy import create_engine
        if migration_url.startswith('postgres://'):
            migration_url = migration_url.replace('postgres://', 'postgresql://', 1)
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
