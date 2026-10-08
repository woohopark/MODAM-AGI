"""Actual three-process HTTP/MCP/SQLite integration; model output is a stated fixture."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest
from pydantic import SecretStr

from modam.chat.database import Database, DatabaseAuthority
from modam.chat.models import User
from modam.config import Settings
from modam.engine import Engine
from modam.mcp_gateway import MCPGateway, resource_access
from modam.observability import Observer
from modam.schemas import GroundedAnswer, Plan, Request, ToolCall
from modam.tools import CallContext, ToolError, ToolRegistry

ROOT = Path(__file__).parents[3]
for project in ["rag", "ontology"]:
    sys.path.insert(0, str(ROOT / f"modam-{project}" / "src"))


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live(tmp_path):
    from modam_ontology.contracts import Definition, Snapshot
    from modam_ontology.store import Store as OntologyStore
    from modam_rag.contracts import Document
    from modam_rag.store import Store as RagStore

    database = Database(f"sqlite:///{tmp_path}/agi.db")
    database.migrate_for_tests()
    uid = database.create_user("fixture-integration", "fixture-password-123")
    with database.sessions.begin() as db:
        db.get(User, uid).grants = [
            {"action": action, "scope": "poc-warehouse"}
            for action in ["documents.read", "inventory.read"]
        ]
    rag = RagStore(tmp_path / "rag.db")
    document = Document.model_validate(
        {
            **json.loads((ROOT / "modam-rag/fixtures/policy.json").read_text()),
            "as_of": datetime.now(UTC).isoformat(),
        }
    )
    document.subjects = [uid]
    rag.ingest(document, expected_version=0)
    ontology = OntologyStore(tmp_path / "ontology.db")
    definition = Definition.model_validate_json(
        (ROOT / "modam-ontology/fixtures/definition.json").read_text()
    )
    proposal = ontology.propose(definition, "fixture-reviewer", "합성 실행")
    ontology.decide(proposal, "fixture-reviewer", True, "테스트 자료 검토")
    snapshot = Snapshot.model_validate(
        {
            **json.loads((ROOT / "modam-ontology/fixtures/snapshot.json").read_text()),
            "as_of": datetime.now(UTC).isoformat(),
        }
    )
    for node in snapshot.nodes:
        node.subjects = [uid]
    ontology.ingest(snapshot, expected_version=0)
    ports = {name: unused_port() for name in ["agi", "rag", "ontology"]}
    keys = {
        "rag": "fixture-rag-key-at-least-32-bytes-long",
        "ontology": "fixture-ontology-key-at-least-32-bytes-long",
    }
    settings = Settings(
        rag_mcp_url=f"http://127.0.0.1:{ports['rag']}/mcp",
        ontology_mcp_url=f"http://127.0.0.1:{ports['ontology']}/mcp",
        rag_service_key=SecretStr(keys["rag"]),
        ontology_service_key=SecretStr(keys["ontology"]),
    )
    processes = []
    logs = []
    try:
        for name in ["agi", "rag", "ontology"]:
            env = os.environ.copy()
            if name == "agi":
                env.update(
                    MODAM_DATABASE_URL=f"sqlite:///{tmp_path}/agi.db",
                    MODAM_RAG_SERVICE_KEY=keys["rag"],
                    MODAM_ONTOLOGY_SERVICE_KEY=keys["ontology"],
                    MODAM_RAG_MCP_URL=settings.rag_mcp_url,
                    MODAM_ONTOLOGY_MCP_URL=settings.ontology_mcp_url,
                )
                script = "from modam.chat.api import create_app; import uvicorn; "
                python = ROOT / "modam-agi/.venv/bin/python"
                script += (
                    f"uvicorn.run(create_app(), host='127.0.0.1', port={ports[name]}, "
                    "access_log=False, log_level='warning')"
                )
            else:
                env.update(
                    KNOWLEDGE_SERVICE_KEY=keys[name],
                    KNOWLEDGE_PORT=str(ports[name]),
                    KNOWLEDGE_DATABASE_PATH=str(tmp_path / f"{name}.db"),
                    KNOWLEDGE_AUTHORITY_URL=f"http://127.0.0.1:{ports['agi']}/internal/tool-authorize",
                )
                python = ROOT / f"modam-{name}/.venv/bin/python"
                script = (
                    f"from modam_{name}.cli import main; import sys; "
                    'sys.argv=["test", "serve"]; main()'
                )
            log = (tmp_path / f"{name}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [str(python), "-c", script],
                    env=env,
                    stdout=log,
                    stderr=log,
                    cwd=ROOT / f"modam-{name}",
                )
            )
        for name, port in ports.items():
            deadline = monotonic() + 20
            while monotonic() < deadline:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                sleep(0.1)
            else:
                raise AssertionError(f"{name} did not start; inspect temporary test logs")
        yield database, uid, settings, rag, ontology, ports
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


class FixedModel:
    provider = "integration-fixture"
    model_id = "deterministic-v1"

    async def plan(self, request, observations, catalog):
        return Plan(
            calls=[
                ToolCall(
                    tool="rag.search", scope="poc-warehouse", arguments={"query": "재고 하한 목표"}
                ),
                ToolCall(
                    tool="ontology.objects.get",
                    scope="poc-warehouse",
                    arguments={"object_ref": "inventory:B:C"},
                ),
            ]
        )

    async def answer(self, message, evidence):
        assert any("108" in e.text for e in evidence)
        assert any("50개" in e.text for e in evidence)
        return GroundedAnswer(
            answer="합성 재고 108개와 목표 50개 근거 확인", citation_ids=[e.ref for e in evidence]
        )


async def test_actual_mcp_combined_engine_and_acl_replay(live):
    database, uid, settings, rag, ontology, ports = live
    gateway = MCPGateway(settings)
    observer = Observer()
    try:
        result = await Engine(
            FixedModel(),
            gateway,
            DatabaseAuthority(database),
            ToolRegistry(),
            observer,
            settings,
            evidence_authorizer=gateway.authorize_evidence,
        ).run(
            Request(
                request_id="integration", subject_ref=uid, message="기업 근거", cloud_allowed=True
            )
        )
        assert result.status == "completed" and result.tool_calls == 2
        assert await gateway.authorize_evidence(uid, result.evidence)
        rag.acl("poc-warehouse", "warehouse-policy", 1, [])
        assert not await gateway.authorize_evidence(uid, result.evidence)
        with database.sessions.begin() as db:
            db.get(User, uid).grants = []
        denied = await gateway.call(
            ToolCall(
                tool="ontology.objects.get",
                scope="poc-warehouse",
                arguments={"object_ref": "inventory:B:C"},
            ),
            CallContext(uid, "inventory.read", "poc-warehouse", "req", "run", "trace"),
        )
        assert denied.status == "denied" and denied.evidence == []
    finally:
        observer.close()


async def test_actual_mcp_paths_and_safe_disconnection(live):
    database, uid, settings, rag, ontology, ports = live
    gateway = MCPGateway(settings)
    response = await gateway.call(
        ToolCall(
            tool="ontology.paths.query",
            scope="poc-warehouse",
            arguments={
                "start_ref": "inventory:B:C",
                "relationship_kinds": ["governed_by", "for_item"],
            },
        ),
        CallContext(uid, "inventory.read", "poc-warehouse", "req", "run", "trace"),
    )
    assert response.status == "completed" and len(response.evidence) == 2
    labels = [
        {"service": "ontology", "scope": e.scope, "action": "inventory.read", "resource_ref": e.ref}
        for e in response.evidence
    ]
    assert await asyncio.to_thread(resource_access, settings, uid, labels)
    ontology.acl("poc-warehouse", "rule:C", [])
    assert not await asyncio.to_thread(resource_access, settings, uid, labels)
    settings.rag_mcp_url = f"http://127.0.0.1:{unused_port()}/mcp"
    with pytest.raises(ToolError) as error:
        await gateway.call(
            ToolCall(tool="rag.search", scope="poc-warehouse", arguments={"query": "재고"}),
            CallContext(uid, "documents.read", "poc-warehouse", "req", "run", "trace"),
        )
    assert error.value.code == "tool_unavailable"
