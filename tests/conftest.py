from collections.abc import Callable, Generator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from modam.api import create_app
from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.llm import ModelError
from modam.models import Base
from modam.schemas import Intent
from modam.security import bootstrap_admin

PASSWORD = "test-only-long-password"


@dataclass
class FakeInterpreter:
    provider: str = "test-double"
    model: str = "fixed-intent"
    intent: Intent = field(default_factory=lambda: Intent(action="inventory.read", scope="B"))
    calls: list[tuple[str, list[str]]] = field(default_factory=list)
    error: str | None = None
    callback: Callable[[], None] | None = None

    def interpret(self, message: str, history: list[str]) -> Intent:
        self.calls.append((message, history))
        if self.callback:
            self.callback()
        if self.error:
            raise ModelError(self.error)
        return self.intent


@dataclass
class Harness:
    client: TestClient
    engine: Engine
    interpreter: FakeInterpreter
    admin_headers: dict[str, str]

    def role(self, name: str, grants: list[dict[str, object]]) -> str:
        response = self.client.post(
            "/v1/admin/roles", json={"name": name, "grants": grants}, headers=self.admin_headers
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    def user(self, username: str, roles: list[str]) -> tuple[str, dict[str, str]]:
        response = self.client.post(
            "/v1/admin/users",
            json={"username": username, "password": PASSWORD, "role_ids": roles},
            headers=self.admin_headers,
        )
        assert response.status_code == 201, response.text
        login = self.client.post(
            "/v1/auth/login", json={"username": username, "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        return response.json()["id"], {"Authorization": "Bearer " + login.json()["token"]}

    def approval(self, headers: dict[str, str], key: str = "order-1", scope: str = "B"):
        return self.client.post(
            "/v1/approvals",
            json={
                "request_key": key,
                "scope": scope,
                "parameters": {"item_id": "C", "quantity": 100, "unit": "개"},
            },
            headers=headers,
        )

    def chat(self, headers: dict[str, str], **changes: object):
        payload = {"request_id": "request-1", "message": "창고 B 재고 조회", "cloud_allowed": True}
        payload.update(changes)
        return self.client.post("/v1/chat", json=payload, headers=headers)


@pytest.fixture
def harness(tmp_path) -> Generator[Harness, None, None]:
    engine = make_engine("sqlite:///" + str(tmp_path / "test.db"))
    Base.metadata.create_all(engine)
    with session_factory(engine)() as db:
        bootstrap_admin(db, "admin", PASSWORD)
    fake = FakeInterpreter()
    app = create_app(
        Settings(database_url="sqlite:///:memory:", groq_api_key=SecretStr("")), fake, engine
    )
    with TestClient(app) as client:
        login = client.post("/v1/auth/login", json={"username": "admin", "password": PASSWORD})
        assert login.status_code == 200
        yield Harness(client, engine, fake, {"Authorization": "Bearer " + login.json()["token"]})
    engine.dispose()
