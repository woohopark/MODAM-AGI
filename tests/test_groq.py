import httpx
import pytest
from pydantic import SecretStr

from modam.config import Settings
from modam.llm import GroqInterpreter, ModelError


def settings():
    return Settings(groq_api_key=SecretStr("test-placeholder"))


def test_groq_contract_uses_json_and_fixed_destination():
    def reply(request):
        import json

        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][-1]["content"] == "창고 B 재고"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"action":"inventory.read","scope":"B"}'}}]},
        )

    result = GroqInterpreter(settings(), httpx.MockTransport(reply)).interpret("창고 B 재고", [])
    assert result.action == "inventory.read"
    assert result.scope == "B"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "model_authentication_failed"),
        (429, "model_rate_limited"),
        (500, "model_unavailable"),
        (302, "model_unavailable"),
    ],
)
def test_remote_errors_are_safe(status, code):
    def reply(request):
        return httpx.Response(status, text="sensitive upstream error test-placeholder")

    with pytest.raises(ModelError) as exc:
        GroqInterpreter(settings(), httpx.MockTransport(reply)).interpret("hello", [])
    assert exc.value.code == code
    assert "sensitive" not in str(exc.value)
    assert "test-placeholder" not in str(exc.value)


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"action":"admin.manage"}',
        '{"action":"inventory.read","execute_sql":"DROP TABLE users"}',
        '{"action":"procurement.propose","quantity":true}',
    ],
)
def test_invalid_model_outputs_cannot_become_tools(content):
    def reply(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with pytest.raises(ModelError, match="model_invalid_response"):
        GroqInterpreter(settings(), httpx.MockTransport(reply)).interpret("hello", [])


def test_timeout_preserves_no_sensitive_remote_details():
    def reply(request):
        raise httpx.ReadTimeout("sensitive timeout", request=request)

    with pytest.raises(ModelError, match="model_timeout"):
        GroqInterpreter(settings(), httpx.MockTransport(reply)).interpret("hello", [])
