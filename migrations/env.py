from alembic import context

from modam.config import Settings
from modam.db import make_engine
from modam.models import Base


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(
            url=Settings().database_url,
            target_metadata=Base.metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = make_engine(Settings().database_url)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()


run_migrations()
