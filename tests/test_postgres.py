import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from conftest import PASSWORD, FakeInterpreter, Harness
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from modam.api import create_app
from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.models import Approval, Audit, ChatRun
from modam.security import bootstrap_admin


@pytest.fixture(scope="module")
def postgres_harness():
    url = os.environ.get("MODAM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MODAM_TEST_DATABASE_URL to a fresh isolated modam_test_* database")
    assert make_url(url).database.startswith("modam_test_")
    engine = make_engine(url)
    assert inspect(engine).get_table_names() == [], "Integration database must be empty"
    previous = os.environ.get("MODAM_DATABASE_URL")
    os.environ["MODAM_DATABASE_URL"] = url
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with session_factory(engine)() as db:
            bootstrap_admin(db, "admin", PASSWORD)
        fake = FakeInterpreter()
        app = create_app(Settings(database_url=url, groq_api_key=SecretStr("")), fake, engine)
        with TestClient(app) as client:
            token = client.post(
                "/v1/auth/login", json={"username": "admin", "password": PASSWORD}
            ).json()["token"]
            yield Harness(client, engine, fake, {"Authorization": "Bearer " + token})
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("MODAM_DATABASE_URL", None)
        else:
            os.environ["MODAM_DATABASE_URL"] = previous


@pytest.mark.postgres
def test_postgres_migration_vector_and_restart_persistence(postgres_harness):
    h = postgres_harness
    assert h.client.get("/health/ready").status_code == 200
    with h.engine.connect() as connection:
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        distance = connection.scalar(text("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector"))
        assert abs(distance) < 0.00001
    role = h.role("buyer", [{"action": "procurement.propose", "scopes": ["B"]}])
    _, headers = h.user("buyer", [role])
    original = h.approval(headers).json()
    restarted = create_app(h.client.app.state.settings, h.interpreter, h.engine)
    with TestClient(restarted) as client:
        response = client.get("/v1/approvals", headers=headers)
        assert response.status_code == 200
        assert response.json()[0]["id"] == original["id"]


@pytest.mark.postgres
def test_concurrent_approval_requests_do_not_duplicate(postgres_harness):
    h = postgres_harness
    role = h.role("concurrent-buyer", [{"action": "procurement.propose", "scopes": ["B"]}])
    _, headers = h.user("concurrent-buyer", [role])
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(workers.map(lambda _: h.approval(headers, key="same-key"), range(4)))
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    with session_factory(h.engine)() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Approval).where(Approval.request_key == "same-key")
            )
            == 1
        )


@pytest.mark.postgres
def test_concurrent_chat_calls_model_once(postgres_harness):
    h = postgres_harness
    role = h.role("concurrent-reader", [{"action": "inventory.read", "scopes": ["B"]}])
    _, headers = h.user("concurrent-reader", [role])
    entered, release = Event(), Event()

    def wait_for_duplicate():
        entered.set()
        assert release.wait(5), "Duplicate request test did not finish"

    h.interpreter.callback = wait_for_duplicate
    original_calls = len(h.interpreter.calls)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(h.chat, headers)
            assert entered.wait(5)
            duplicate = h.chat(headers)
            release.set()
            assert duplicate.status_code == 409
            assert future.result(timeout=5).status_code == 200
        assert len(h.interpreter.calls) == original_calls + 1
        with session_factory(h.engine)() as db:
            assert db.scalar(select(func.count()).select_from(ChatRun)) == 1
    finally:
        release.set()
        h.interpreter.callback = None


@pytest.mark.postgres
def test_concurrent_decisions_produce_one_audit(postgres_harness):
    h = postgres_harness
    roles = h.client.get("/v1/admin/roles", headers=h.admin_headers).json()
    buyer = next(role["id"] for role in roles if role["name"] == "buyer")
    _, headers = h.user("decision-requester", [buyer])
    role = h.role("decision-approver", [{"action": "procurement.approve", "scopes": ["B"]}])
    _, approver = h.user("decision-approver", [role])
    row = h.approval(headers, key="concurrent-decision").json()
    path = f"/v1/approvals/{row['id']}/decision"
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(
            workers.map(
                lambda decision: h.client.post(path, json={"decision": decision}, headers=approver),
                ["approved", "rejected"],
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    with session_factory(h.engine)() as db:
        events = list(db.scalars(select(Audit).where(Audit.event == "approval.decision")))
        assert sum(event.details["approval_id"] == row["id"] for event in events) == 1
