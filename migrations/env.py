import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from noesis.persistence.models import Base

config = context.config
if os.environ.get("NOESIS_DB_PATH"):
    config.set_main_option("sqlalchemy.url", f"sqlite:///{os.environ['NOESIS_DB_PATH']}")
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    # FTS5's virtual table and shadow tables are managed explicitly by the
    # migration; Alembic cannot model them through SQLAlchemy metadata.
    return not (type_ == "table" and name.startswith("learning_fts"))


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, include_object=include_object, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
