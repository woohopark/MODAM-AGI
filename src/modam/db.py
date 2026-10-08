from sqlite3 import Connection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if ":memory:" in url:
            engine = create_engine(
                url, poolclass=StaticPool, connect_args={"check_same_thread": False}
            )
        else:
            engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: Connection, record: ConnectionPoolEntry) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
