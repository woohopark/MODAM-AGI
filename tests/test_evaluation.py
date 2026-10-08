import pytest


def test_independent_scenario_and_latency_report(tmp_path):
    from modam.evaluation import evaluate

    report = evaluate(mode="offline", repeats=2, warmup=1)
    assert report["measured_runs"] == 2
    assert report["warmup_runs"] == 1
    assert report["mode"] == "offline"
    assert report["passed_runs"] == 2
    assert report["real_llm_calls"] == 0
    assert report["metrics"]["workflow"]["count"] == 2
    assert report["metrics"]["workflow"]["p95_ms"] >= report["metrics"]["workflow"]["p50_ms"]
    assert report["results"][0]["rag_correct"] == 7


def test_no_key_is_a_blocker_not_a_passing_groq_evaluation(monkeypatch):
    from modam.evaluation import evaluate

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        evaluate(mode="groq", repeats=1, warmup=0)


def test_percentiles_and_empty_measurements():
    from modam.evaluation import statistics

    assert statistics([10, 20, 30, 40, 50])["p95_ms"] == 50
    with pytest.raises(ValueError):
        statistics([])


def test_real_http_transport_runs_the_same_business_scenario():
    from modam.evaluation import evaluate

    report = evaluate(mode="offline", repeats=1, warmup=0, transport="http")
    assert report["transport"] == "loopback-HTTP"
    assert report["passed_runs"] == 1
    assert report["results"][0]["rag_correct"] == 7
    assert report["real_llm_calls"] == 0
