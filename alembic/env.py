from __future__ import annotations

from importlib import import_module
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

from services.common.accounts import registry
from services.common.config import get_settings, validated_workspace
from services.common.db import Base
from services.retrieval.vector_store import VECTOR_TABLES

# Register all ORM tables before Alembic reads the metadata.
import_module("services.common.models")
import_module("services.common.search_models")
import_module("services.common.library_models")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def include_name(name, type_, parent_names):
    return type_ != "table" or name not in VECTOR_TABLES


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    def migrate(connection, root=True):
        context.configure(
            connection=connection,
            target_metadata=[target_metadata, registry] if root else target_metadata,
            compare_type=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()

    with connectable.connect() as connection:
        migrate(connection)
        if connection.dialect.name == "postgresql" and inspect(connection).has_table(
            "library_accounts"
        ):
            names = connection.scalars(
                text("SELECT workspace FROM library_accounts WHERE workspace <> 'public'")
            ).all()
            connection.commit()
            for name in names:
                validated_workspace(name)
                with connectable.connect() as scoped:
                    scoped.exec_driver_sql(f'SET search_path TO "{name}"')
                    scoped.commit()
                    migrate(scoped, root=False)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
