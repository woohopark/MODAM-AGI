"""Independent functional and latency evaluation against fresh synthetic data."""

import hashlib
import math
import os
import platform
import socket
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Literal

import httpx
from fastapi.testclient import TestClient

from modam.api import create_app
from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.llm import GroqInterpreter, Interpreter
from modam.models import Base
from modam.sample import RecordedInterpreter, load_dataset, seed_sample
from modam.schemas import GroundedAnswer, Intent

Mode = Literal["offline", "groq"]
Transport = Literal["asgi", "http"]


def statistics(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("Cannot compute latency statistics for zero measurements")
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)

    return {
        "count": len(values),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "mean_ms": round(sum(values) / len(values), 3),
        "max_ms": round(max(values), 3),
    }


class MeteredInterpreter:
    def __init__(self, delegate: Interpreter) -> None:
        self.delegate = delegate
        self.provider, self.model = delegate.provider, delegate.model
        self.calls: list[dict[str, Any]] = []

    def interpret(self, message: str, history: list[str]) -> Intent:
        started = perf_counter()
        try:
            return self.delegate.interpret(message, history)
        finally:
            self.calls.append(
                {"kind": "interpret", "elapsed_ms": (perf_counter() - started) * 1000}
            )

    def answer(self, question: str, contexts: list[dict[str, Any]]) -> GroundedAnswer:
        started = perf_counter()
        try:
            return self.delegate.answer(question, contexts)
        finally:
            self.calls.append({"kind": "answer", "elapsed_ms": (perf_counter() - started) * 1000})


class ScenarioFailure(Exception):
    pass


def run_scenario(
    client: TestClient | httpx.Client, credentials: dict[str, str], mode: Mode
) -> dict[str, Any]:
    headers = {}
    for name, password in credentials.items():
        response = client.post("/v1/auth/login", json={"username": name, "password": password})
        if response.status_code != 200:
            raise ScenarioFailure("sample_login")
        headers[name] = {"Authorization": "Bearer " + response.json()["token"]}
    field, manager, accountant = [
        headers[name] for name in ("sample_field", "sample_inventory", "sample_accounting")
    ]
    latencies: dict[str, list[float]] = defaultdict(list)
    checks: list[dict[str, Any]] = []
    workflow_start = perf_counter()
    model_attempts = 0

    def request(
        label: str,
        method: str,
        path: str,
        auth: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> Any:
        started = perf_counter()
        response = client.request(method, path, headers=auth, json=payload)
        latencies[label].append((perf_counter() - started) * 1000)
        return response

    def check(label: str, success: bool) -> None:
        checks.append({"check": label, "passed": bool(success)})
        if not success:
            raise ScenarioFailure(label)

    def chat(label: str, message: str, auth: dict[str, str]) -> dict[str, Any]:
        response = request(
            label,
            "POST",
            "/v1/chat",
            auth,
            {"request_id": label, "message": message, "cloud_allowed": mode == "groq"},
        )
        check(label + ":http", response.status_code == 200)
        body = dict(response.json())
        nonlocal model_attempts
        model_attempts += int(body.get("model_calls", 0))
        check(label + ":model", body.get("status") != "failed")
        for phase, duration in body.get("timings_ms", {}).items():
            latencies["agent:" + phase].append(float(duration))
        return body

    rag_correct = 0
    try:
        denied = chat("denied_purchase", "창고 B의 물품 C 100개 발주해 줘", accountant)
        check(
            "accounting_cannot_purchase",
            denied["status"] == "denied" and not denied["data"] and not denied["evidence"],
        )
        for i, case in enumerate(load_dataset()["rag_cases"]):
            answer = chat(f"rag_{i}", case["question"], accountant)
            correct = (
                answer["status"] == "completed"
                and case["expected_text"] in answer["message"]
                and any(e["source_id"] == case["source_id"] for e in answer["evidence"])
            )
            rag_correct += int(correct)
            checks.append({"check": f"rag_{i}:facts_and_source", "passed": correct})
        check("rag_5_of_7", rag_correct >= 5)
        event = {
            "event_id": "synthetic-erp-outbound-1",
            "scope": "B",
            "item_id": "C",
            "quantity": 100,
            "confirmed": True,
        }
        issued = request("inventory_issue", "POST", "/v1/inventory/events", field, event)
        check("issue_http", issued.status_code == 200)
        check(
            "stock_8_reorder_42",
            issued.json()["quantity"] == 8 and issued.json()["suggested_quantity"] == 42,
        )
        repeat = request("event_replay", "POST", "/v1/inventory/events", field, event)
        check("event_dedup", repeat.status_code == 200 and repeat.json() == issued.json())
        graph = request("graph", "GET", "/v1/graph?scope=B&start=warehouse:B", field)
        check(
            "related_objects",
            graph.status_code == 200
            and {"inventory:B:C", "item:C", "rule:B:C"} <= {n["id"] for n in graph.json()["nodes"]},
        )
        alerts = request("notifications", "GET", "/v1/notifications", manager)
        check(
            "manager_alert",
            alerts.status_code == 200
            and len(alerts.json()) == 1
            and alerts.json()[0]["details"]["suggested_quantity"] == 42,
        )
        analysis = chat("inventory_analysis", "창고 B 물품 C 재고와 후속 업무를 확인해줘", field)
        check(
            "stock_analysis",
            analysis["status"] == "completed"
            and analysis["data"]["suggested_quantity"] == 42
            and bool(analysis["evidence"]),
        )
        proposal = chat("purchase_proposal", "창고 B 물품 C 42개 발주 제안해줘", field)
        check("approval_required", proposal["status"] == "awaiting_approval")
        approval_id = proposal["data"]["approval_id"]
        forbidden = request(
            "forbidden_approval",
            "POST",
            f"/v1/approvals/{approval_id}/decision",
            accountant,
            {"decision": "approved"},
        )
        check("accounting_cannot_approve", forbidden.status_code == 404)
        premature = request(
            "premature_execution", "POST", f"/v1/approvals/{approval_id}/execute", manager
        )
        check("no_execution_before_approval", premature.status_code == 409)
        decision = request(
            "approval",
            "POST",
            f"/v1/approvals/{approval_id}/decision",
            manager,
            {"decision": "approved"},
        )
        check("manager_approves", decision.status_code == 200)
        draft = request("draft", "POST", f"/v1/approvals/{approval_id}/execute", manager)
        check(
            "draft_created",
            draft.status_code == 200
            and draft.json()["quantity"] == 42
            and not draft.json()["erp_registered"],
        )
        replay = request("draft_replay", "POST", f"/v1/approvals/{approval_id}/execute", manager)
        check(
            "draft_dedup", replay.status_code == 200 and replay.json()["id"] == draft.json()["id"]
        )
        stock = request("final_stock", "GET", "/v1/inventory/B/C", field)
        check(
            "pending_orders_prevent_repeat",
            stock.status_code == 200
            and stock.json()["quantity"] == 8
            and stock.json()["pending_quantity"] == 42
            and stock.json()["suggested_quantity"] == 0,
        )
        result: dict[str, Any] = {"passed": True}
    except ScenarioFailure as exc:
        result = {"passed": False, "failed_check": str(exc)}
    result.update(
        {
            "rag_correct": rag_correct,
            "model_call_attempts": model_attempts,
            "checks": checks,
            "latencies": dict(latencies),
            "workflow_ms": (perf_counter() - workflow_start) * 1000,
        }
    )
    return result


def evaluate(
    mode: Mode = "offline", repeats: int = 5, warmup: int = 1, transport: Transport = "asgi"
) -> dict[str, Any]:
    if not 1 <= repeats <= 50 or not 0 <= warmup <= 10:
        raise ValueError("repeats must be 1..50 and warmup 0..10")
    settings = Settings()
    if mode == "groq" and not settings.groq_api_key.get_secret_value():
        raise ValueError("GROQ_API_KEY must be injected securely for actual Groq evaluation")
    if transport not in ("asgi", "http"):
        raise ValueError("Unknown evaluation transport")
    if mode not in ("offline", "groq"):
        raise ValueError("Unknown evaluation mode")
    results, measurements = [], defaultdict(list)
    warmup_outcomes, real_calls = [], 0
    for index in range(repeats + warmup):
        with TemporaryDirectory(prefix="modam-scenario-") as directory:
            engine = make_engine("sqlite:///" + str(Path(directory) / "scenario.db"))
            Base.metadata.create_all(engine)
            with session_factory(engine)() as db:
                credentials = seed_sample(db)
            delegate: Interpreter = (
                RecordedInterpreter() if mode == "offline" else GroqInterpreter(settings)
            )
            metered = MeteredInterpreter(delegate)
            app = create_app(settings, metered, engine)
            try:
                with (
                    TestClient(app) if transport == "asgi" else socket_client(directory, mode)
                ) as client:
                    result = run_scenario(client, credentials, mode)
                if index < warmup:
                    warmup_outcomes.append(result["passed"])
                    continue
                results.append(result)
                # Failed runs are retained, but never mixed into successful latency summaries.
                if result["passed"]:
                    measurements["workflow"].append(result["workflow_ms"])
                    for label, durations in result["latencies"].items():
                        measurements[label].extend(durations)
                    for call in metered.calls:
                        measurements["model:" + call["kind"]].append(call["elapsed_ms"])
                if mode == "groq":
                    real_calls += int(result["model_call_attempts"])
            finally:
                engine.dispose()
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        revision = "unknown"
    return {
        "mode": mode,
        "provider": "recorded-fixture" if mode == "offline" else "groq",
        "model": "warehouse-poc-v1" if mode == "offline" else settings.groq_model,
        "dataset_version": load_dataset()["version"],
        "git_commit": revision,
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True)
        ),
        "dataset_sha256": hashlib.sha256(json_dataset()).hexdigest(),
        "transport": "in-process-ASGI" if transport == "asgi" else "loopback-HTTP",
        "database": "fresh SQLite per run",
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "warmup_runs": warmup,
        "warmup_passed": sum(warmup_outcomes),
        "measured_runs": repeats,
        "passed_runs": sum(r["passed"] for r in results),
        "real_llm_calls": real_calls,
        "metrics": {key: statistics(values) for key, values in measurements.items()},
        "results": results,
        "timing_excludes": ["data seeding", "schema creation", "login", "warmup"],
        "limitations": [
            "Offline mode measures reference responses, not LLM intelligence.",
            "ASGI timings omit sockets; loopback HTTP omits WAN and production concurrency.",
            "Retrieval is sparse lexical vectors, not semantic embedding.",
        ],
    }


def json_dataset() -> bytes:
    import json

    return json.dumps(load_dataset(), sort_keys=True, ensure_ascii=False).encode()


@contextmanager
def socket_client(directory: str, mode: Mode) -> Generator[httpx.Client, None, None]:
    """Run a real server against the already seeded disposable scenario database."""
    child_env = dict(os.environ)
    child_env["MODAM_SCENARIO_DATABASE"] = str(Path(directory) / "scenario.db")
    child_env["MODAM_SCENARIO_MODE"] = mode
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "modam.demo:scenario_app",
                "--factory",
                "--fd",
                str(listener.fileno()),
            ],
            env=child_env,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False
            ) as client:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise ValueError("Scenario HTTP server exited before readiness")
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        raise ValueError("Scenario HTTP readiness timed out")
                    time.sleep(0.1)
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
