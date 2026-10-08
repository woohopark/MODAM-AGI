"""Seed an isolated demo or evaluate complete scenarios without touching the app DB."""

import argparse
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import cast

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from modam.api import create_app
from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.evaluation import Mode, Transport, evaluate
from modam.llm import GroqInterpreter
from modam.models import DatasetSeed, Role, User
from modam.sample import RecordedInterpreter, load_dataset, seed_sample
from modam.security import hash_password

LOCAL = Path(".local")
DATABASE = LOCAL / "demo.db"
CREDENTIALS = LOCAL / "demo-credentials.json"


def seed_demo() -> None:
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    url = "sqlite:///" + str(DATABASE.resolve())
    previous = os.environ.get("MODAM_DATABASE_URL")
    os.environ["MODAM_DATABASE_URL"] = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("MODAM_DATABASE_URL", None)
        else:
            os.environ["MODAM_DATABASE_URL"] = previous
    engine = make_engine(url)
    try:
        with session_factory(engine)() as db:
            seeded = db.get(DatasetSeed, load_dataset()["version"])
            if seeded:
                if not CREDENTIALS.exists():
                    raise ValueError(
                        "Demo credentials file is missing; passwords cannot be recovered"
                    )
                additions = ensure_demo_admin(db)
                if additions:
                    retain_credentials(additions)
                print("Existing demo retained; no inventory or passwords were reset.")
                return
            if CREDENTIALS.exists():
                raise ValueError("Existing credentials file preserved; demo state does not match")
            credentials = seed_sample(db)
            credentials.update(ensure_demo_admin(db))
        descriptor = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(credentials, output)
    finally:
        engine.dispose()
    print("Synthetic warehouse sample seeded in .local/demo.db.")
    print("Accounts: sample_admin, sample_accounting, sample_field, sample_inventory.")
    print("Generated passwords are stored only in .local/demo-credentials.json (0600).")


def ensure_demo_admin(db: Session) -> dict[str, str]:
    if db.get(DatasetSeed, load_dataset()["version"]) is None:
        raise ValueError("Demo admin requires the synthetic dataset marker")
    if db.scalar(select(User.id).where(User.username == "sample_admin")):
        return {}
    grants = [{"action": "admin.manage", "scopes": ["*"]}]
    role = db.scalar(select(Role).where(Role.name == "sample-admin"))
    if role is not None and role.grants != grants:
        raise ValueError("Demo admin role collision")
    if role is None:
        role = Role(name="sample-admin", grants=grants)
        db.add(role)
        db.flush()
    password = secrets.token_urlsafe(24)
    db.add(User(username="sample_admin", password_hash=hash_password(password), roles=[role]))
    db.commit()
    return {"sample_admin": password}


def retain_credentials(additions: dict[str, str]) -> None:
    if CREDENTIALS.is_symlink():
        raise ValueError("Demo credentials must be a regular generated file")
    existing = json.loads(CREDENTIALS.read_text())
    descriptor, name = tempfile.mkstemp(dir=LOCAL, prefix=".demo-credentials-")
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({**existing, **additions}, output)
        os.replace(name, CREDENTIALS)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def demo_app(mode: Mode) -> FastAPI:
    if not DATABASE.exists():
        raise ValueError("Run demo seed first")
    settings = Settings(database_url="sqlite:///" + str(DATABASE.resolve()))
    engine = make_engine(settings.database_url)
    with session_factory(engine)() as db:
        if db.get(DatasetSeed, load_dataset()["version"]) is None:
            raise ValueError("Selected database is not the versioned synthetic demo")
    if mode == "groq" and not settings.groq_api_key.get_secret_value():
        raise ValueError("GROQ_API_KEY must be injected securely")
    model = RecordedInterpreter() if mode == "offline" else GroqInterpreter(settings)
    return create_app(settings, model, engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="MODAM synthetic demo and independent evaluation")
    parser.add_argument(
        "command",
        choices=[
            "seed",
            "serve",
            "evaluate",
            "chat",
            "issue",
            "approve",
            "execute",
            "inventory",
            "notifications",
            "graph",
        ],
    )
    parser.add_argument("--mode", choices=["offline", "groq"], default="offline")
    parser.add_argument("--transport", choices=["asgi", "http"], default="asgi")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--output", type=Path, default=LOCAL / "reports" / "latest.json")
    parser.add_argument("--user", default="sample_field")
    parser.add_argument("--message")
    parser.add_argument("--quantity", type=int, default=100)
    parser.add_argument("--event-id", default="manual-outbound-1")
    parser.add_argument("--approval-id")
    args = parser.parse_args()
    try:
        if args.command == "seed":
            seed_demo()
        elif args.command == "serve":
            uvicorn.run(demo_app(cast(Mode, args.mode)), host="127.0.0.1", port=args.port)
        elif args.command != "evaluate":
            demo_action(args)
        else:
            report = evaluate(
                cast(Mode, args.mode), args.repeat, args.warmup, cast(Transport, args.transport)
            )
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        key: report[key]
                        for key in ("mode", "measured_runs", "passed_runs", "real_llm_calls")
                    },
                    ensure_ascii=False,
                )
            )
            print("Report:", args.output)
            if report["passed_runs"] != report["measured_runs"]:
                raise SystemExit(1)
    except ValueError as exc:
        parser.error(str(exc))
    except httpx.HTTPError:
        parser.error("Demo HTTP request failed; check the matching demo server port")


def demo_action(args: argparse.Namespace) -> None:
    from uuid import uuid4

    if not CREDENTIALS.exists():
        raise ValueError("Run demo seed first")
    credentials = json.loads(CREDENTIALS.read_text())
    if args.user not in credentials:
        raise ValueError("Unknown generated sample account")
    with httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}", trust_env=False, timeout=120
    ) as client:
        login = client.post(
            "/v1/auth/login", json={"username": args.user, "password": credentials[args.user]}
        )
        if login.status_code != 200:
            raise ValueError("Sample login failed")
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        try:
            if args.command == "chat":
                if not args.message:
                    raise ValueError("--message is required")
                response = client.post(
                    "/v1/chat",
                    headers=headers,
                    json={
                        "message": args.message,
                        "request_id": str(uuid4()),
                        "cloud_allowed": args.mode == "groq",
                    },
                )
            elif args.command == "issue":
                response = client.post(
                    "/v1/inventory/events",
                    headers=headers,
                    json={
                        "event_id": args.event_id,
                        "scope": "B",
                        "item_id": "C",
                        "quantity": args.quantity,
                        "confirmed": True,
                    },
                )
            elif args.command in ("approve", "execute"):
                if not args.approval_id:
                    raise ValueError("--approval-id is required")
                suffix = "decision" if args.command == "approve" else "execute"
                response = client.post(
                    f"/v1/approvals/{args.approval_id}/{suffix}",
                    headers=headers,
                    json={"decision": "approved"} if args.command == "approve" else None,
                )
            else:
                paths = {
                    "inventory": "/v1/inventory/B/C",
                    "notifications": "/v1/notifications",
                    "graph": "/v1/graph?scope=B&start=warehouse:B",
                }
                response = client.get(paths[args.command], headers=headers)
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
            if response.status_code >= 400:
                raise SystemExit(1)
        finally:
            client.post("/v1/auth/logout", headers=headers)


def scenario_app() -> FastAPI:
    path = os.environ.get("MODAM_SCENARIO_DATABASE")
    mode = os.environ.get("MODAM_SCENARIO_MODE", "offline")
    if not path or mode not in ("offline", "groq"):
        raise ValueError("Explicit scenario database and model mode are required")
    settings = Settings(database_url="sqlite:///" + str(Path(path).resolve()))
    engine = make_engine(settings.database_url)
    with session_factory(engine)() as db:
        if db.get(DatasetSeed, load_dataset()["version"]) is None:
            raise ValueError("Scenario database must contain the synthetic dataset marker")
    model = RecordedInterpreter() if mode == "offline" else GroqInterpreter(settings)
    return create_app(settings, model, engine)


if __name__ == "__main__":
    main()
