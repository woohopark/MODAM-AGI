"""Synthetic boundary evaluation only. Fixture adapters cannot be a production model."""

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from modam.config import Settings
from modam.engine import Engine
from modam.llm import GroqModel
from modam.observability import Observer
from modam.schemas import Evidence, Grant, GroundedAnswer, Plan, Request, ToolCall, ToolResult
from modam.tools import CallContext, DisconnectedGateway, ToolError, ToolRegistry


class EvaluationAuthority:
    """Synthetic verified identity at the test boundary; not an authentication service."""

    def __init__(self, grants: list[Grant]) -> None:
        self.grants = grants

    async def is_active(self, subject: str) -> bool:
        return subject == "synthetic:evaluator"

    async def can_send(self, subject: str, scope: str | None) -> bool:
        return subject == "synthetic:evaluator"

    async def permits(self, subject: str, action: str, scope: str) -> bool:
        return subject == "synthetic:evaluator" and any(
            g.action == action and (scope in g.scopes or "*" in g.scopes) for g in self.grants
        )


class EvaluationModel:
    provider = "boundary-fixture"
    model_id = "agi-scenarios-v1"

    def __init__(self, plan: Plan) -> None:
        self._plan = plan

    async def plan(
        self, request: Request, observations: list[str], catalog: list[dict[str, object]]
    ) -> Plan:
        return self._plan

    async def answer(self, message: str, evidence: list[Evidence]) -> GroundedAnswer:
        return GroundedAnswer(
            answer="\n".join(e.text for e in evidence), citation_ids=[e.ref for e in evidence]
        )


class EvaluationGateway:
    def __init__(self, response: ToolResult, retry: bool) -> None:
        self.response, self.retry = response, retry
        self.calls = 0

    async def call(self, call: ToolCall, context: CallContext) -> ToolResult:
        self.calls += 1
        if self.retry and self.calls == 1:
            raise ToolError("tool_timeout", retryable=True)
        return self.response


def dataset_bytes() -> bytes:
    return files("modam").joinpath("data/agi-scenarios-v1.json").read_bytes()


def load_dataset() -> dict[str, Any]:
    return dict(json.loads(dataset_bytes()))


def latency(values: list[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    return {
        "count": len(values),
        "p50_ms": ordered[math.ceil(len(values) * 0.5) - 1] if values else None,
        "p95_ms": ordered[math.ceil(len(values) * 0.95) - 1] if values else None,
    }


def revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


async def evaluate(
    *,
    mode: str = "boundary",
    repeats: int = 1,
    warmup: int = 0,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"boundary", "groq"} or not 1 <= repeats <= 20 or not 0 <= warmup <= 5:
        raise ValueError("Invalid evaluation options")
    data = dataset or load_dataset()
    settings = Settings()
    report: dict[str, Any] = {
        "dataset_version": data["version"],
        "dataset_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "git_sha": revision(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
            )
        )
        if revision() != "unknown"
        else None,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode,
        "model_id": settings.groq_model if mode == "groq" else "boundary-fixture",
        "prompt_version": settings.prompt_version,
        "contract_version": "0.1",
        "config_version": settings.config_version,
        "repeats": repeats,
        "warmup": warmup,
        "real_mcp_connected": False,
        "real_groq_attempts": 0,
        "status": "unrun",
        "results": [],
        "limitations": [
            "Boundary fixtures do not measure Groq accuracy or MCP integration.",
            "Groq mode evaluates planning with disconnected MCP tools only.",
            "Identity, persistence, approval and mutation flows are not implemented.",
        ],
    }
    if mode == "groq" and not settings.groq_api_key.get_secret_value():
        report.update(status="blocked", reason="model_key_missing", latency=latency([]))
        return report
    measured: list[float] = []
    stages: dict[str, list[float]] = {}
    warmup_failed = False
    for repetition in range(warmup + repeats):
        for case in data["cases"]:
            # Real Groq mode only checks read planning against a disconnected gateway.
            if mode == "groq" and case["scenario"] != "read":
                continue
            observer = Observer()
            real_model = GroqModel(settings) if mode == "groq" else None
            model = real_model or EvaluationModel(Plan.model_validate(case["plan"]))
            gateway = (
                DisconnectedGateway()
                if real_model
                else EvaluationGateway(
                    ToolResult.model_validate(case["response"]), case["scenario"] == "retry"
                )
            )
            runner = Engine(
                model,
                gateway,
                EvaluationAuthority([Grant.model_validate(g) for g in case["grants"]]),
                ToolRegistry(),
                observer,
                settings,
            )
            try:
                result = await runner.run(
                    Request(
                        request_id=f"{repetition}:{case['case_id']}",
                        subject_ref="synthetic:evaluator",
                        message=case["message"],
                        cloud_allowed=case["scenario"] != "no_cloud",
                    )
                )
                expected = "not_available" if real_model else case["expected_status"]
                checks = {
                    "status": result.status == expected,
                    "tool_count": result.tool_calls
                    == (1 if real_model else case["expected_tools"]),
                    "trace": bool(observer.spans()),
                }
                if expected == "completed":
                    checks["fact"] = case["expected_fact"] in result.message
                    checks["citation"] = bool(result.evidence)
                passed = all(checks.values())
                if real_model:
                    report["real_groq_attempts"] += real_model.attempts
                if repetition < warmup:
                    warmup_failed |= not passed
                    continue
                report["results"].append(
                    {
                        "case_id": case["case_id"],
                        "repeat": repetition - warmup,
                        "status": "passed" if passed else "failed",
                        "checks": checks,
                        "run_status": result.status,
                        "error_code": result.error_code,
                        "duration_ms": result.elapsed_ms,
                        "model_usage": real_model.last_usage if real_model else None,
                    }
                )
                if passed:
                    measured.append(result.elapsed_ms)
                    for span in observer.spans():
                        if span.start_time is not None and span.end_time is not None:
                            stages.setdefault(span.name, []).append(
                                (span.end_time - span.start_time) / 1_000_000
                            )
            finally:
                observer.close()
                if real_model:
                    await real_model.close()
    report["warmup_failed"] = warmup_failed
    report["status"] = (
        "passed"
        if report["results"]
        and all(r["status"] == "passed" for r in report["results"])
        and not warmup_failed
        else "failed"
    )
    report["latency"] = latency(measured)
    report["stage_latency"] = {stage: latency(values) for stage, values in stages.items()}
    report["passed"] = sum(r["status"] == "passed" for r in report["results"])
    report["failed"] = len(report["results"]) - report["passed"]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MODAM foundation evaluation; no production writes"
    )
    parser.add_argument("--mode", choices=["boundary", "groq"], default="boundary")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path(".local/reports/foundation.json"))
    args = parser.parse_args()
    report = asyncio.run(evaluate(mode=args.mode, repeats=args.repeat, warmup=args.warmup))
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False))
    raise SystemExit(
        0 if report["status"] == "passed" else 2 if report["status"] == "blocked" else 1
    )


if __name__ == "__main__":
    main()
