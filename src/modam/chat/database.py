"""Transactions and authentication. HTTP and model calls stay outside transactions."""

import hashlib
import secrets
from time import time
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from modam.chat.models import Base, SessionToken, User

_hasher = PasswordHasher()
_dummy = _hasher.hash(secrets.token_urlsafe(32))


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate_for_tests(self) -> None:
        """SQLite fixture only; production uses Alembic, never startup create_all."""
        if self.engine.dialect.name != "sqlite":
            raise ValueError("Use Alembic for PostgreSQL")
        Base.metadata.create_all(self.engine)

    def create_user(self, username: str, password: str, *, admin: bool = False) -> str:
        if not 3 <= len(username) <= 80 or len(password) < 12:
            raise ValueError("Username 3..80 and password >=12 characters required")
        with self.sessions.begin() as db:
            user = User(
                id=str(uuid4()),
                username=username,
                password_hash=_hasher.hash(password),
                roles=["admin"] if admin else ["user"],
                grants=[],
                active=True,
                cloud_allowed=True,
            )
            db.add(user)
            return user.id

    def login(self, username: str, password: str) -> str | None:
        with self.sessions.begin() as db:
            user = db.scalar(select(User).where(User.username == username))
            try:
                valid = _hasher.verify(user.password_hash if user else _dummy, password)
            except VerificationError:
                return None
            if not valid or not user or not user.active:
                return None
            if _hasher.check_needs_rehash(user.password_hash):
                user.password_hash = _hasher.hash(password)
            token = secrets.token_urlsafe(48)
            db.add(SessionToken(digest=digest(token), user_id=user.id, expires=time() + 86400))
            return token

    def authenticate(self, db: Session, token: str) -> User | None:
        record = db.get(SessionToken, digest(token))
        if not record or record.expires <= time():
            return None
        user = db.get(User, record.user_id)
        return user if user and user.active else None


class DatabaseAuthority:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def is_active(self, subject: str) -> bool:
        with self.database.sessions() as db:
            user = db.get(User, subject)
            return bool(user and user.active)

    async def can_send(self, subject: str, scope: str | None) -> bool:
        with self.database.sessions() as db:
            user = db.get(User, subject)
            return bool(user and user.active and user.cloud_allowed)

    async def permits(self, subject: str, action: str, scope: str) -> bool:
        with self.database.sessions() as db:
            user = db.get(User, subject)
            return bool(
                user
                and user.active
                and any(g.get("action") == action and g.get("scope") == scope for g in user.grants)
            )
