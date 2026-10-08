from sqlalchemy import func, select

from modam.db import session_factory
from modam.models import Approval


def setup_users(harness):
    proposer = harness.role("proposer", [{"action": "procurement.propose", "scopes": ["B"]}])
    approver = harness.role("approver", [{"action": "procurement.approve", "scopes": ["B"]}])
    requester_id, request_headers = harness.user("requester", [proposer])
    approver_id, approve_headers = harness.user("approver", [approver])
    return requester_id, request_headers, approver_id, approve_headers


def test_idempotency_scopes_and_approval_not_execution(harness):
    _, headers, _, approver = setup_users(harness)
    first = harness.approval(headers)
    assert first.status_code == 201
    assert first.json()["status"] == "pending"
    assert harness.approval(headers).json()["id"] == first.json()["id"]
    assert harness.approval(headers, scope="A").status_code == 403
    assert harness.approval(headers, key="bad-scope", scope="*").status_code == 403
    payload = {
        "request_key": "order-1",
        "scope": "B",
        "parameters": {"item_id": "C", "quantity": 200, "unit": "개"},
    }
    assert harness.client.post("/v1/approvals", json=payload, headers=headers).status_code == 409
    path = f"/v1/approvals/{first.json()['id']}/decision"
    assert (
        harness.client.post(path, json={"decision": "approved"}, headers=headers).status_code == 404
    )
    decision = harness.client.post(path, json={"decision": "approved"}, headers=approver)
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert "executed" not in decision.text
    assert (
        harness.client.post(path, json={"decision": "approved"}, headers=approver).status_code
        == 200
    )
    assert (
        harness.client.post(path, json={"decision": "rejected"}, headers=approver).status_code
        == 409
    )
    with session_factory(harness.engine)() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 1


def test_requester_permission_revoked_before_approval(harness):
    requester_id, headers, _, approver = setup_users(harness)
    approval = harness.approval(headers).json()
    role = harness.role("reader", [{"action": "documents.read", "scopes": ["public"]}])
    harness.client.patch(
        f"/v1/admin/users/{requester_id}", json={"role_ids": [role]}, headers=harness.admin_headers
    )
    assert (
        harness.client.post(
            f"/v1/approvals/{approval['id']}/decision",
            json={"decision": "approved"},
            headers=approver,
        ).status_code
        == 409
    )
    assert harness.client.get("/v1/approvals", headers=headers).json() == []


def test_approver_permission_revoked(harness):
    _, headers, approver_id, approver = setup_users(harness)
    approval = harness.approval(headers).json()
    role = harness.role("reader", [{"action": "documents.read", "scopes": ["public"]}])
    harness.client.patch(
        f"/v1/admin/users/{approver_id}", json={"role_ids": [role]}, headers=harness.admin_headers
    )
    assert (
        harness.client.post(
            f"/v1/approvals/{approval['id']}/decision",
            json={"decision": "approved"},
            headers=approver,
        ).status_code
        == 404
    )


def test_rejection_and_invalid_quantity(harness):
    _, headers, _, approver = setup_users(harness)
    row = harness.approval(headers).json()
    result = harness.client.post(
        f"/v1/approvals/{row['id']}/decision", json={"decision": "rejected"}, headers=approver
    )
    assert result.json()["status"] == "rejected"
    for quantity in [0, -1, True, "100"]:
        assert (
            harness.client.post(
                "/v1/approvals",
                json={
                    "request_key": "invalid",
                    "scope": "B",
                    "parameters": {"item_id": "C", "quantity": quantity, "unit": "개"},
                },
                headers=headers,
            ).status_code
            == 422
        )
