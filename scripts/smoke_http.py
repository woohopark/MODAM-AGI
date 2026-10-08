"""Verify a real HTTP process against a disposable PostgreSQL database."""

import os
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.security import bootstrap_admin

root_url = make_url(Settings().database_url)
if root_url.get_backend_name() != "postgresql":
    raise SystemExit("Configure PostgreSQL or run scripts/start_postgres.py first")
name = "modam_test_" + uuid4().hex
owner_engine = make_engine(root_url.render_as_string(hide_password=False))
with owner_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    connection.execute(text(f'CREATE DATABASE "{name}"'))
test_url = root_url.set(database=name).render_as_string(hide_password=False)
child_env = dict(os.environ)
child_env["MODAM_DATABASE_URL"] = test_url
child_env["GROQ_API_KEY"] = ""  # This smoke checks failure handling, not real Cloud inference.
process = None
try:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=child_env, check=True)
    engine = make_engine(test_url)
    password = secrets.token_urlsafe(32)
    with session_factory(engine)() as db:
        bootstrap_admin(db, "smoke-admin", password)
    engine.dispose()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "modam.main:app", "--fd", str(listener.fileno())],
            env=child_env,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
        ) as client:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("HTTP process exited before readiness")
                try:
                    if client.get("/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("HTTP process did not become ready")
                time.sleep(0.1)
            response = client.post(
                "/v1/auth/login", json={"username": "smoke-admin", "password": password}
            )
            assert response.status_code == 200
            admin = {"Authorization": "Bearer " + response.json()["token"]}
            role = client.post(
                "/v1/admin/roles",
                json={
                    "name": "buyer",
                    "grants": [{"action": "procurement.propose", "scopes": ["B"]}],
                },
                headers=admin,
            )
            assert role.status_code == 201
            assert (
                client.post(
                    "/v1/admin/users",
                    json={
                        "username": "buyer",
                        "password": password,
                        "role_ids": [role.json()["id"]],
                    },
                    headers=admin,
                ).status_code
                == 201
            )
            login = client.post("/v1/auth/login", json={"username": "buyer", "password": password})
            buyer = {"Authorization": "Bearer " + login.json()["token"]}
            assert client.get("/v1/admin/users", headers=buyer).status_code == 403
            payload = {
                "scope": "B",
                "request_key": "smoke-order",
                "parameters": {"item_id": "C", "quantity": 100, "unit": "개"},
            }
            first = client.post("/v1/approvals", json=payload, headers=buyer)
            second = client.post("/v1/approvals", json=payload, headers=buyer)
            assert first.status_code == second.status_code == 201
            assert first.json()["id"] == second.json()["id"]
            chat = client.post(
                "/v1/chat",
                json={"request_id": "smoke-chat", "message": "물품 발주", "cloud_allowed": True},
                headers=buyer,
            )
            assert chat.status_code == 200
            assert chat.json()["status"] == "failed"
            assert chat.json()["error_code"] == "model_key_missing"
            assert client.get("/v1/admin/audit", headers=admin).status_code == 200
    print("HTTP smoke passed: login, admin boundary, approval dedup, missing-key handling.")
finally:
    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    with owner_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    owner_engine.dispose()
