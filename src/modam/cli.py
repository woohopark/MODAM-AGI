import argparse
import getpass
import re

from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.security import bootstrap_admin


def main() -> None:
    parser = argparse.ArgumentParser(description="MODAM administration")
    parser.add_argument("command", choices=["bootstrap-admin"])
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]{1,100}", args.username):
        parser.error("Username must contain 1-100 valid identifier characters")
    password = getpass.getpass("Admin password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12 or len(password) > 256 or password != confirmation:
        parser.error("Password must be 12-256 characters and confirmations must match")
    engine = make_engine(Settings().database_url)
    try:
        with session_factory(engine)() as db:
            bootstrap_admin(db, args.username, password)
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        engine.dispose()
    print("Admin created; no business permissions were granted automatically.")


if __name__ == "__main__":
    main()
