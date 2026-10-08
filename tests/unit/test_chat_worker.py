import asyncio
from time import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from modam.chat.api import create_app
from modam.chat.database import Database
from modam.chat.models import Event, Run, User
from modam.chat.repository import history
from modam.chat.worker import Worker
from modam.config import Settings


@pytest.fixture
def setup(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/state.db")
    db.migrate_for_tests()
    uid = db.create_user("alice", "testing-password-123", admin=True)
    client = TestClient(create_app(db))
    token = client.post(
        "/v1/auth/login", json={"username": "alice", "password": "testing-password-123"}
    ).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    conv = client.post("/v1/conversations", json={"mode": "general"}).json()["id"]
    return db, client, conv, uid


def submit(client, conv, request_id="request-123"):
    return client.post(
        f"/v1/conversations/{conv}/runs",
        json={"request_id": request_id, "message": "질문", "cloud_allowed": True},
    )


async def test_canonical_history_and_final_event_replay(setup, monkeypatch):
    db, client, conv, _ = setup
    seen = []

    async def chat(model, message):
        seen.append(model.history)
        return "답변"

    monkeypatch.setattr("modam.chat.worker.GroqModel.chat", chat)
    for index in range(3):
        queued = submit(client, conv, f"request-{index}").json()
        worker = Worker(db, Settings())
        assert worker.claim() == queued["id"]
        await worker.execute(queued["id"])
        assert client.get(f"/v1/runs/{queued['id']}").json()["status"] == "completed"
    assert [len(messages) for messages in seen] == [0, 2, 4]
    events = client.get(f"/v1/runs/{queued['id']}/events").text
    assert "event: accepted" in events and "event: done" in events
    cursor = int(events.split("id: ")[-1].splitlines()[0])
    assert client.get(f"/v1/runs/{queued['id']}/events?after={cursor}").text == ""
    assert (
        client.get(
            f"/v1/runs/{queued['id']}/events", headers={"Last-Event-ID": "invalid"}
        ).status_code
        == 422
    )
    assert client.delete(f"/v1/conversations/{conv}").status_code == 204


async def test_cancellation_interrupts_model_and_excludes_failed_context(setup, monkeypatch):
    db, client, conv, _ = setup
    interrupted = asyncio.Event()

    async def slow(model, message):
        try:
            await asyncio.sleep(30)
        finally:
            interrupted.set()
        return "late"

    monkeypatch.setattr("modam.chat.worker.GroqModel.chat", slow)
    queued = submit(client, conv).json()
    assert submit(client, conv, "another-123").status_code == 409
    assert client.delete(f"/v1/conversations/{conv}").status_code == 409
    worker = Worker(db, Settings())
    worker.claim()
    task = asyncio.create_task(worker.execute(queued["id"]))
    await asyncio.sleep(0.02)
    client.post(f"/v1/runs/{queued['id']}/cancel")
    await task
    assert interrupted.is_set()
    with db.sessions() as session:
        assert history(session, conv) == []
    assert client.get(f"/v1/runs/{queued['id']}").json()["answer"] == ""


def test_cancel_before_creation_and_expired_worker_not_retried(setup):
    db, client, conv, _ = setup
    assert client.post("/v1/requests/before-creation/cancel").status_code == 204
    assert submit(client, conv, "before-creation").json()["status"] == "cancelled"
    queued = submit(client, conv, "lost-worker").json()
    worker = Worker(db, Settings())
    assert worker.claim() == queued["id"]
    with db.sessions.begin() as session:
        run = session.get(Run, queued["id"])
        run.lease_until = time() - 1
    restarted = Worker(db, Settings())
    assert restarted.recover() == 1
    assert restarted.claim() is None
    assert client.get(f"/v1/runs/{queued['id']}").json()["error_code"] == "worker_lost"


async def test_current_cloud_policy_revocation_prevents_answer(setup, monkeypatch):
    db, client, conv, uid = setup

    async def chat(model, message):
        with db.sessions.begin() as session:
            session.get(User, uid).cloud_allowed = False
        return "MUST_NOT_RELEASE"

    monkeypatch.setattr("modam.chat.worker.GroqModel.chat", chat)
    queued = submit(client, conv).json()
    worker = Worker(db, Settings())
    worker.claim()
    await worker.execute(queued["id"])
    result = client.get(f"/v1/runs/{queued['id']}").json()
    assert result["outcome"] == "denied"
    assert "MUST_NOT_RELEASE" not in result["answer"]


def test_validation_policy_and_retention(setup):
    db, client, conv, uid = setup
    for message in [" ", "x" * 4001]:
        assert (
            client.post(
                f"/v1/conversations/{conv}/runs",
                json={"request_id": "invalid-123", "message": message, "cloud_allowed": True},
            ).status_code
            == 422
        )
    assert (
        client.post(
            f"/v1/conversations/{conv}/runs",
            json={
                "request_id": "claims-123",
                "message": "질문",
                "cloud_allowed": True,
                "subject_ref": "admin",
            },
        ).status_code
        == 422
    )
    added = client.post(
        "/v1/admin/users", json={"username": "bob", "password": "other-password-123"}
    )
    assert added.status_code == 201
    user_id = added.json()["id"]
    policy = {
        "active": True,
        "cloud_allowed": True,
        "roles": ["user"],
        "grants": [{"action": "documents.read", "scope": "logistics"}],
    }
    assert client.put(f"/v1/admin/users/{user_id}/policy", json=policy).status_code == 204
    assert client.put(f"/v1/admin/users/{uid}/policy", json=policy).status_code == 409
    queued = submit(client, conv).json()
    worker = Worker(db, Settings())
    worker.claim()
    worker.finish(queued["id"], "completed", "protected-answer", None, policy["grants"])
    assert "protected-answer" not in client.get(f"/v1/runs/{queued['id']}").json()["answer"]
    assert "protected-answer" not in client.get(f"/v1/runs/{queued['id']}/events").text
    assert "protected-answer" not in client.post(f"/v1/runs/{queued['id']}/cancel").text
    assert "protected-answer" not in submit(client, conv).text
    assert "protected-answer" not in client.get(f"/v1/conversations/{conv}/messages").text
    from modam.chat.models import Conversation

    with db.sessions.begin() as session:
        session.get(Conversation, conv).updated = time() - 31 * 86400
    worker.cleanup()
    assert client.get("/v1/conversations").json() == []
    with db.sessions() as session:
        assert list(session.scalars(select(Event))) == []
