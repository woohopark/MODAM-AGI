import pytest

from modam.evaluation import evaluate, latency, load_dataset


async def test_dataset_evaluation_and_failed_expectations():
    report = await evaluate(repeats=2, warmup=1)
    assert report["status"] == "passed"
    assert report["passed"] == 28 and report["failed"] == 0
    assert report["latency"]["count"] == 28
    assert report["real_groq_attempts"] == 0
    data = load_dataset()
    data["cases"][0]["expected_fact"] = "incorrect-reference-fact"
    report = await evaluate(dataset=data)
    assert report["status"] == "failed" and report["failed"] == 1
    assert report["latency"]["count"] == 13


async def test_no_key_is_blocked_not_passed(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    report = await evaluate(mode="groq")
    assert report["status"] == "blocked" and report["real_groq_attempts"] == 0
    assert report["results"] == []


async def test_invalid_options_and_empty_latency():
    with pytest.raises(ValueError):
        await evaluate(repeats=0)
    assert latency([])["p95_ms"] is None
