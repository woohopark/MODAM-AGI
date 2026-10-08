from modam.config import Settings
from modam.mcp_gateway import mint, resource_access
from modam.tools import CallContext


def test_delegation_separates_service_scope_and_expiry():
    token = mint(
        b"x" * 32, "rag", CallContext("alice", "documents.read", "warehouse", "req", "run", "trace")
    )
    import base64
    import json

    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert claims["sub"] == "alice" and claims["scope"] == "warehouse" and claims["aud"] == "rag"
    assert "trace" not in claims


def test_history_fails_closed_when_resource_service_is_missing():
    assert not resource_access(
        Settings(),
        "alice",
        [
            {
                "service": "rag",
                "resource_ref": "rag:policy:v1:0:0",
                "scope": "warehouse",
                "action": "documents.read",
            }
        ],
    )


async def test_resource_authorization_batches_refs_and_checks_every_batch(monkeypatch):
    import json
    from datetime import UTC, datetime

    import httpx
    from pydantic import SecretStr

    from modam.mcp_gateway import MCPGateway
    from modam.schemas import Evidence

    actual_client = httpx.Client
    actual_async_client = httpx.AsyncClient
    denied_ref = None
    calls = []

    def service(request):
        refs = json.loads(request.content)["refs"]
        calls.append(refs)
        return httpx.Response(200, json={"allowed": len(refs) <= 20 and denied_ref not in refs})

    monkeypatch.setattr(
        "modam.mcp_gateway.httpx.Client",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(service), **kwargs),
    )
    monkeypatch.setattr(
        "modam.mcp_gateway.httpx.AsyncClient",
        lambda **kwargs: actual_async_client(transport=httpx.MockTransport(service), **kwargs),
    )
    settings = Settings(rag_mcp_url="http://rag:8201/mcp", rag_service_key=SecretStr("r" * 32))
    items = [
        Evidence(
            scope="warehouse",
            ref=f"rag:policy:v1:0:{i}",
            source_ref="rag:policy",
            version="1",
            as_of=datetime.now(UTC),
            text="근거",
            cloud_allowed=True,
        )
        for i in range(45)
    ]
    labels = [
        {"service": "rag", "action": "documents.read", "scope": "warehouse", "resource_ref": e.ref}
        for e in items
    ]
    assert resource_access(settings, "alice", labels)
    assert await MCPGateway(settings).authorize_evidence("alice", items)
    assert all(len(batch) <= 20 for batch in calls)
    assert set().union(*map(set, calls)) == {e.ref for e in items}
    denied_ref = items[-1].ref
    assert not resource_access(settings, "alice", labels)
    assert not await MCPGateway(settings).authorize_evidence("alice", items)
