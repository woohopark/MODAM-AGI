"""Opt-in real Groq HTTP smoke: reads credentials from a protected file, not arguments."""

import argparse
import json
import uuid
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:3000")
parser.add_argument("--credentials-file", type=Path, default=Path(".local/chat-runtime.json"))
parser.add_argument("--output", type=Path, default=Path(".local/reports/chat-live-http.json"))
args = parser.parse_args()
c = json.loads(args.credentials_file.read_text())
with httpx.Client(
    base_url=args.base_url,
    trust_env=False,
    timeout=100,
    headers={"X-Modam-Request": "1", "Origin": args.base_url},
) as client:
    login = client.post(
        "/api/auth/login", json={"username": c["admin_username"], "password": c["admin_password"]}
    )
    assert login.status_code == 200, (login.status_code, login.text)
    assert "token" not in login.json()
    assert "HttpOnly" in login.headers["set-cookie"]
    conv = client.post("/api/conversations", json={"mode": "general"}).json()["id"]
    reports = []
    for message, word in [
        ("내 프로젝트 이름은 파란달이고 언어는 Python이야. 두 정보를 기억해줘.", "파란달"),
        ("내 프로젝트 이름과 언어를 말해줘.", "Python"),
        ("그 프로젝트 이름만 정확히 말해줘.", "파란달"),
    ]:
        payload = {"message": message, "request_id": str(uuid.uuid4()), "cloud_allowed": True}
        r = client.post(f"/api/conversations/{conv}/runs", json=payload)
        assert r.status_code == 202, r.text
        job = r.json()["id"]
        assert client.post(f"/api/conversations/{conv}/runs", json=payload).json()["id"] == job
        with client.stream("GET", f"/api/runs/{job}/events") as events:
            assert events.status_code == 200
            seq = [line for line in events.iter_lines() if line.startswith("id:")]
            assert seq
        result = client.get(f"/api/runs/{job}").json()
        assert result["status"] == "completed", result
        assert word in result["answer"], result
        reports.append({"status": result["status"], "context_assertion": True, "events": len(seq)})
    restored = client.get(f"/api/conversations/{conv}/messages").json()
    assert len(restored) == 6
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "three_turns": reports,
                "restore_messages": len(restored),
                "httponly": True,
                "conversation_id": conv,
            },
            indent=2,
        )
    )
    print(
        "Real BFF -> AGI -> PostgreSQL worker -> Groq: 3 turns passed; "
        "6 persisted messages; SSE; dedup; HttpOnly"
    )
