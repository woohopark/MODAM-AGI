from datetime import timedelta

from conftest import PASSWORD
from sqlalchemy import select

from modam.db import session_factory
from modam.models import AuthSession, User, now
from modam.security import bootstrap_admin


def test_login_logout_and_no_plaintext_storage(harness):
    client = harness.client
    assert client.get("/health/ready").json() == {"status": "ready"}
    assert client.get("/v1/auth/me").status_code == 401
    assert (
        client.post("/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code
        == 401
    )
    assert (
        client.post("/v1/auth/login", json={"username": "missing", "password": "wrong"}).status_code
        == 401
    )
    me = client.get("/v1/auth/me", headers=harness.admin_headers)
    assert me.status_code == 200
    assert "password" not in me.text
    with session_factory(harness.engine)() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        row = db.scalar(select(AuthSession))
        assert row.token_hash != harness.admin_headers["Authorization"].split()[1]
        try:
            bootstrap_admin(db, "second-admin", PASSWORD)
        except ValueError:
            pass
        else:
            raise AssertionError("Bootstrap must reject existing databases")
    assert client.post("/v1/auth/logout", headers=harness.admin_headers).status_code == 204
    assert client.get("/v1/auth/me", headers=harness.admin_headers).status_code == 401


def test_expired_session(harness):
    with session_factory(harness.engine)() as db:
        row = db.scalar(select(AuthSession))
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert harness.client.get("/v1/auth/me", headers=harness.admin_headers).status_code == 401


def test_roles_are_action_scope_pairs_and_admin_not_business_superuser(harness):
    inventory = harness.role("inventory", [{"action": "inventory.read", "scopes": ["B"]}])
    purchase = harness.role("purchase", [{"action": "procurement.propose", "scopes": ["A"]}])
    _, headers = harness.user("multi", [inventory, purchase])
    for action, scope, expected in [
        ("inventory.read", "B", True),
        ("procurement.propose", "A", True),
        ("procurement.propose", "B", False),
        ("inventory.read", "A", False),
    ]:
        response = harness.client.post(
            "/v1/permissions/check", json={"action": action, "scope": scope}, headers=headers
        )
        assert response.json() == {"allowed": expected}
    assert harness.client.get("/v1/admin/users", headers=headers).status_code == 403
    assert harness.approval(harness.admin_headers).status_code == 403


def test_role_revocation_and_deactivation_are_immediate(harness):
    inventory = harness.role("inventory", [{"action": "inventory.read", "scopes": ["B"]}])
    docs = harness.role("docs", [{"action": "documents.read", "scopes": ["public"]}])
    user_id, headers = harness.user("worker", [inventory])
    harness.client.patch(
        f"/v1/admin/users/{user_id}", json={"role_ids": [docs]}, headers=harness.admin_headers
    )
    response = harness.client.post(
        "/v1/permissions/check", json={"action": "inventory.read", "scope": "B"}, headers=headers
    )
    assert response.json() == {"allowed": False}
    harness.client.patch(
        f"/v1/admin/users/{user_id}", json={"active": False}, headers=harness.admin_headers
    )
    assert harness.client.get("/v1/auth/me", headers=headers).status_code == 401
    assert (
        harness.client.post(
            "/v1/auth/login", json={"username": "worker", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_duplicate_and_invalid_admin_inputs(harness):
    role = harness.role("docs", [{"action": "documents.read", "scopes": ["public"]}])
    assert (
        harness.client.post(
            "/v1/admin/roles",
            json={"name": "docs", "grants": [{"action": "documents.read", "scopes": ["public"]}]},
            headers=harness.admin_headers,
        ).status_code
        == 409
    )
    harness.user("worker", [role])
    for password, role_ids, expected in [
        (PASSWORD, [role], 409),
        ("short", [role], 422),
        (PASSWORD, ["missing"], 422),
    ]:
        response = harness.client.post(
            "/v1/admin/users",
            json={"username": "worker", "password": password, "role_ids": role_ids},
            headers=harness.admin_headers,
        )
        assert response.status_code == expected


def test_last_active_admin_cannot_be_removed(harness):
    me = harness.client.get("/v1/auth/me", headers=harness.admin_headers).json()
    reader = harness.role("reader", [{"action": "inventory.read", "scopes": ["B"]}])
    for patch in [{"active": False}, {"role_ids": [reader]}]:
        response = harness.client.patch(
            f"/v1/admin/users/{me['id']}", json=patch, headers=harness.admin_headers
        )
        assert response.status_code == 409
    assert harness.client.get("/v1/admin/users", headers=harness.admin_headers).status_code == 200
