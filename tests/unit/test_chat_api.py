from fastapi.testclient import TestClient

from modam.chat.api import create_app
from modam.chat.database import Database


def test_auth_ownership_idempotency_and_cancel(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/chat.db")
    db.migrate_for_tests()
    db.create_user("alice", "test-password-123", admin=True)
    db.create_user("bob", "test-password-456")
    with TestClient(create_app(db)) as client:
        assert client.get("/v1/conversations").status_code == 401
        token = client.post(
            "/v1/auth/login", json={"username": "alice", "password": "test-password-123"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post(
            "/v1/conversations", headers=headers, json={"mode": "general"}
        ).json()
        payload = {"request_id": "unique-request-1", "message": "안녕", "cloud_allowed": True}
        first = client.post(
            f"/v1/conversations/{conversation['id']}/runs", headers=headers, json=payload
        )
        assert first.status_code == 202
        duplicate = client.post(
            f"/v1/conversations/{conversation['id']}/runs", headers=headers, json=payload
        )
        assert duplicate.json()["id"] == first.json()["id"]
        conflict = client.post(
            f"/v1/conversations/{conversation['id']}/runs",
            headers=headers,
            json={**payload, "message": "different"},
        )
        assert conflict.status_code == 409
        bob = client.post(
            "/v1/auth/login", json={"username": "bob", "password": "test-password-456"}
        ).json()["token"]
        assert (
            client.get(
                f"/v1/runs/{first.json()['id']}", headers={"Authorization": f"Bearer {bob}"}
            ).status_code
            == 404
        )
        assert (
            client.post(f"/v1/runs/{first.json()['id']}/cancel", headers=headers).json()["status"]
            == "cancelled"
        )
        assert client.post("/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/v1/session", headers=headers).status_code == 401
