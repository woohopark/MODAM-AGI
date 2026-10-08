import hashlib
import secrets
from datetime import UTC, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from modam.models import Audit, AuthSession, Role, User, now

_hasher = PasswordHasher()
_dummy_hash = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    try:
        valid = _hasher.verify(stored or _dummy_hash, password)
        return bool(stored) and valid
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db: Session, user: User, ttl: int) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    row = AuthSession(
        token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(seconds=ttl)
    )
    db.add(row)
    return token, row


def session_user(db: Session, token: str) -> User | None:
    row = db.get(AuthSession, token_hash(token))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now():
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.active else None


def allowed(user: User, action: str, scope: str | None) -> bool:
    if not user.active:
        return False
    for role in user.roles:
        for grant in role.grants:
            if grant.get("action") == action:
                scopes = grant.get("scopes", [])
                # An unspecified scope requires a true global grant.
                if "*" in scopes or (scope is not None and scope in scopes):
                    return True
    return False


def has_action(user: User, action: str) -> bool:
    return user.active and any(
        grant.get("action") == action for role in user.roles for grant in role.grants
    )


def audit(
    db: Session,
    user: User | None,
    event: str,
    outcome: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        Audit(
            user_id=user.id if user else None,
            event=event,
            outcome=outcome,
            details=details or {},
            request_id=request_id,
        )
    )


def bootstrap_admin(db: Session, username: str, password: str) -> User:
    if db.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Bootstrap is only permitted for an empty user database")
    role = Role(name="admin", grants=[{"action": "admin.manage", "scopes": ["*"]}])
    db.add(role)
    db.flush()
    user = User(username=username, password_hash=hash_password(password), roles=[role])
    db.add(user)
    db.flush()
    audit(db, user, "admin.bootstrap", "created")
    db.commit()
    return user
