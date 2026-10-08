import json

import httpx
import pytest
from pydantic import SecretStr

from modam.config import Settings
from modam.llm import GroqModel, ModelError
from modam.schemas import Request


def request():
    return Request(
        request_id="r", subject_ref="synthetic:user", message="회사 규정", cloud_allowed=True
    )


async def test_contract_fixed_destination_json_usage_and_no_claims():
    def reply(req):
        assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
        payload = json.loads(req.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert "subject_ref" not in payload["messages"][-1]["content"]
        assert "synthetic:user" not in payload["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"question":"어떤 규정인가요?"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            },
        )

    model = GroqModel(
        Settings(groq_api_key=SecretStr("test-placeholder")), transport=httpx.MockTransport(reply)
    )
    try:
        assert (await model.plan(request(), [], [])).question
        assert model.last_usage["total_tokens"] == 13
        assert model.attempts == 1
    finally:
        await model.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "model_authentication_failed"),
        (429, "model_rate_limited"),
        (500, "model_unavailable"),
        (302, "model_unavailable"),
    ],
)
async def test_http_errors_never_expose_remote_body_or_key(status, code):
    model = GroqModel(
        Settings(groq_api_key=SecretStr("secret-test-key")),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, text="sensitive-company-text")
        ),
    )
    try:
        with pytest.raises(ModelError) as exc:
            await model.plan(request(), [], [])
        assert exc.value.code == code
        assert "secret" not in str(exc.value) and "sensitive" not in str(exc.value)
    finally:
        await model.close()


@pytest.mark.parametrize(
    "content",
    [
        "bad-json",
        '{"calls":[]}',
        '{"unsupported":true,"execute_sql":"DROP"}',
        '{"calls":[{"tool":"rag.search","scope":"company","arguments":{},"user_id":"admin"}]}',
    ],
)
async def test_bad_model_structure_is_rejected(content):
    model = GroqModel(
        Settings(groq_api_key=SecretStr("test-placeholder")),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        ),
    )
    try:
        with pytest.raises(ModelError, match="model_invalid_response"):
            await model.plan(request(), [], [])
    finally:
        await model.close()


async def test_missing_key_timeout_and_missing_usage():
    def timeout(req):
        raise httpx.ReadTimeout("sensitive", request=req)

    for key, code in [("", "model_key_missing"), ("test-placeholder", "model_timeout")]:
        model = GroqModel(
            Settings(groq_api_key=SecretStr(key)), transport=httpx.MockTransport(timeout)
        )
        try:
            with pytest.raises(ModelError, match=code):
                await model.plan(request(), [], [])
            assert model.last_usage is None
            assert model.attempts == (0 if not key else 1)
        finally:
            await model.close()


async def test_removed_model_has_precise_safe_error_code():
    model = GroqModel(
        Settings(groq_api_key=SecretStr("secret-test-key")),
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="sensitive error")),
    )
    try:
        with pytest.raises(ModelError, match="model_not_found"):
            await model.plan(request(), [], [])
    finally:
        await model.close()
