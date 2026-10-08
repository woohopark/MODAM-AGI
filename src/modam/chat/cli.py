"""Explicit account bootstrap. Password is read with getpass, never command arguments."""

import argparse
from getpass import getpass

import uvicorn

from modam.chat.database import Database
from modam.config import Settings


def bootstrap() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    password = getpass("Password (minimum 12 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    Database(Settings().database_url.get_secret_value()).create_user(
        args.username, password, admin=args.admin
    )
    print("Account created")


def api() -> None:
    settings = Settings()
    uvicorn.run(
        "modam.chat.api:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        access_log=False,
    )
