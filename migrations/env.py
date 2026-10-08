from alembic import context
from sqlalchemy import create_engine

from modam.chat.models import Base
from modam.config import Settings

engine = create_engine(Settings().database_url.get_secret_value())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
