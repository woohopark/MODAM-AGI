from sqlalchemy import func, select

from modam.db import session_factory
from modam.models import Approval, User
from modam.schemas import Intent


def load_sample(harness):
    from modam.sample import seed_sample

    with session_factory(harness.engine)() as db:
        credentials = seed_sample(db)
    headers = {}
    for name, password in credentials.items():
        response = harness.client.post(
            "/v1/auth/login", json={"username": name, "password": password}
        )
        assert response.status_code == 200
        headers[name] = {"Authorization": "Bearer " + response.json()["token"]}
    return headers


def test_full_inventory_approval_draft_and_repeat(harness):
    users = load_sample(harness)
    field = users["sample_field"]
    manager = users["sample_inventory"]
    event = {
        "event_id": "erp-outbound-1",
        "scope": "B",
        "item_id": "C",
        "quantity": 100,
        "confirmed": True,
    }
    issued = harness.client.post("/v1/inventory/events", json=event, headers=field)
    assert issued.status_code == 200, issued.text
    assert issued.json()["quantity"] == 8
    assert issued.json()["suggested_quantity"] == 42
    assert (
        harness.client.post("/v1/inventory/events", json=event, headers=field).json()
        == issued.json()
    )
    graph = harness.client.get(
        "/v1/graph", params={"scope": "B", "start": "warehouse:B"}, headers=field
    )
    assert {"inventory:B:C", "rule:B:C", "item:C"} <= {n["id"] for n in graph.json()["nodes"]}
    alerts = harness.client.get("/v1/notifications", headers=manager).json()
    assert len(alerts) == 1 and alerts[0]["details"]["suggested_quantity"] == 42
    harness.interpreter.intent = Intent(
        action="procurement.propose", scope="B", item_id="C", quantity=42, unit="개"
    )
    proposed = harness.chat(field, message="창고 B 물품 C 42개 발주 제안해줘").json()
    assert proposed["status"] == "awaiting_approval"
    approval_id = proposed["data"]["approval_id"]
    assert (
        harness.client.post(
            f"/v1/approvals/{approval_id}/decision", json={"decision": "approved"}, headers=manager
        ).status_code
        == 200
    )
    draft = harness.client.post(f"/v1/approvals/{approval_id}/execute", headers=manager)
    assert draft.status_code == 200, draft.text
    assert draft.json()["quantity"] == 42
    assert (
        harness.client.post(f"/v1/approvals/{approval_id}/execute", headers=manager).json()["id"]
        == draft.json()["id"]
    )
    stock = harness.client.get("/v1/inventory/B/C", headers=field).json()
    assert stock["quantity"] == 8 and stock["pending_quantity"] == 42
    assert stock["suggested_quantity"] == 0
    with session_factory(harness.engine)() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 1


def test_documents_citations_hits_and_unknown_question(harness):
    users = load_sample(harness)
    harness.interpreter.intent = Intent(action="documents.read", scope="company")
    response = harness.chat(users["sample_accounting"], message="회사 발주 승인 규정을 알려줘")
    assert response.json()["status"] == "completed", response.text
    assert "재고 담당자" in response.json()["message"]
    assert any(c["source_id"] == "policy-approval" for c in response.json()["evidence"])
    assert "FINANCE-PRIVATE-EXAMPLE" not in response.text
    hits = harness.client.get("/v1/admin/documents/metrics", headers=harness.admin_headers).json()
    assert any(row["search_hits"] > 0 and row["citations"] > 0 for row in hits)
    empty = harness.chat(
        users["sample_accounting"], request_id="unknown", message="화성 출장 수당은 얼마인가요"
    )
    assert empty.json()["status"] == "clarification"
    assert empty.json()["evidence"] == []


def test_source_change_and_permissions_require_reapproval(harness):
    users = load_sample(harness)
    field, manager = users["sample_field"], users["sample_inventory"]
    approval = harness.approval(field).json()
    assert (
        harness.client.post(
            f"/v1/approvals/{approval['id']}/decision",
            json={"decision": "approved"},
            headers=manager,
        ).status_code
        == 200
    )
    event = {
        "event_id": "changed-source",
        "scope": "B",
        "item_id": "C",
        "quantity": 1,
        "confirmed": True,
    }
    assert harness.client.post("/v1/inventory/events", json=event, headers=field).status_code == 200
    assert (
        harness.client.post(f"/v1/approvals/{approval['id']}/execute", headers=manager).status_code
        == 409
    )


def test_inventory_event_authorization_confirmation_and_underflow(harness):
    users = load_sample(harness)
    event = {"event_id": "evt", "scope": "B", "item_id": "C", "quantity": 100, "confirmed": True}
    assert (
        harness.client.post(
            "/v1/inventory/events", json=event, headers=users["sample_accounting"]
        ).status_code
        == 403
    )
    event["confirmed"] = False
    assert (
        harness.client.post(
            "/v1/inventory/events", json=event, headers=users["sample_field"]
        ).status_code
        == 422
    )
    event["confirmed"] = True
    event["quantity"] = 200
    assert (
        harness.client.post(
            "/v1/inventory/events", json=event, headers=users["sample_field"]
        ).status_code
        == 409
    )
    assert (
        harness.client.get("/v1/inventory/B/C", headers=users["sample_field"]).json()["quantity"]
        == 108
    )


def test_conflicting_rules_do_not_generate_certain_answer(harness):
    users = load_sample(harness)
    added = harness.client.post(
        "/v1/admin/documents",
        json={
            "id": "conflicting",
            "scope": "company",
            "title": "재고 발주 기준",
            "location": "충돌 샘플",
            "version": 1,
            "text": "재고 발주 기준은 20개 미만이다.",
            "facts": {"reorder_threshold": 20},
        },
        headers=harness.admin_headers,
    )
    assert added.status_code == 201
    harness.interpreter.intent = Intent(action="documents.read", scope="company")
    response = harness.chat(users["sample_accounting"], message="재고 발주 기준은 몇 개인가요")
    assert response.json()["status"] == "clarification"
    assert "상충" in response.json()["message"]


def test_seed_is_repeatable_and_preserves_existing_users(harness):
    from modam.sample import seed_sample

    users = load_sample(harness)
    with session_factory(harness.engine)() as db:
        before = db.scalar(select(func.count()).select_from(User))
        assert seed_sample(db) == {}
        assert db.scalar(select(func.count()).select_from(User)) == before
    assert harness.client.get("/v1/auth/me", headers=users["sample_field"]).status_code == 200


def test_approver_permission_revoked_before_draft_execution(harness):
    users = load_sample(harness)
    field, manager = users["sample_field"], users["sample_inventory"]
    approval = harness.approval(field).json()
    assert (
        harness.client.post(
            f"/v1/approvals/{approval['id']}/decision",
            json={"decision": "approved"},
            headers=manager,
        ).status_code
        == 200
    )
    role = harness.role("executor-only", [{"action": "procurement.execute", "scopes": ["B"]}])
    user_id = harness.client.get("/v1/auth/me", headers=manager).json()["id"]
    harness.client.patch(
        f"/v1/admin/users/{user_id}", json={"role_ids": [role]}, headers=harness.admin_headers
    )
    response = harness.client.post(f"/v1/approvals/{approval['id']}/execute", headers=manager)
    assert response.status_code == 409
    assert response.json()["detail"] == "approver_permission_changed"
    assert harness.client.get("/v1/inventory/B/C", headers=field).json()["pending_quantity"] == 0


def test_current_permissions_mask_cached_document_evidence(harness):
    users = load_sample(harness)
    accountant = users["sample_accounting"]
    harness.interpreter.intent = Intent(action="documents.read", scope="company")
    first = harness.chat(accountant, message="회사 발주 승인 규정을 알려줘")
    assert first.json()["evidence"]
    role = harness.role("no-documents", [{"action": "inventory.read", "scopes": ["B"]}])
    user_id = harness.client.get("/v1/auth/me", headers=accountant).json()["id"]
    harness.client.patch(
        f"/v1/admin/users/{user_id}", json={"role_ids": [role]}, headers=harness.admin_headers
    )
    replay = harness.chat(accountant, message="회사 발주 승인 규정을 알려줘").json()
    assert replay["status"] == "denied"
    assert replay["evidence"] == [] and replay["data"] == {}


def test_cloud_document_permission_blocks_context_transmission(harness):
    users = load_sample(harness)
    harness.client.post(
        "/v1/admin/documents",
        json={
            "id": "no-cloud",
            "scope": "company",
            "title": "발주 승인 규정",
            "location": "내부 문서",
            "version": 1,
            "text": "발주 승인은 재고 담당자가 수행한다.",
            "cloud_allowed": False,
        },
        headers=harness.admin_headers,
    )
    harness.interpreter.provider = "groq"
    harness.interpreter.intent = Intent(action="documents.read", scope="company")

    def forbidden_answer(*args):
        raise AssertionError("Restricted document must not be sent to the model")

    harness.interpreter.answer = forbidden_answer
    response = harness.chat(
        users["sample_accounting"], message="회사 발주 승인 규정을 알려줘"
    ).json()
    assert response["status"] == "clarification"
    assert "Cloud" in response["message"]


def test_unknown_citations_fail_instead_of_fabricating_sources(harness):
    from modam.schemas import GroundedAnswer

    users = load_sample(harness)
    harness.interpreter.intent = Intent(action="documents.read", scope="company")
    harness.interpreter.answer = lambda *args: GroundedAnswer(
        answer="unsupported", citation_ids=["invented-source"]
    )
    response = harness.chat(
        users["sample_accounting"], message="회사 발주 승인 규정을 알려줘"
    ).json()
    assert response["status"] == "failed"
    assert response["error_code"] == "model_invalid_citation"
    assert response["evidence"] == []
