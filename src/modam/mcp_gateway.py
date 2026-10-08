"""Trusted catalog -> official MCP transport, signed delegation and live resource ACL."""

import base64
import hashlib
import hmac
from collections import defaultdict
from time import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import Field, ValidationError

from modam.config import Settings
from modam.schemas import Contract, Evidence, ToolCall, ToolResult
from modam.tools import CallContext, ToolError, ToolRegistry


class Claims(Contract):
    sub: str = Field(min_length=1, max_length=100)
    action: str
    scope: str = Field(min_length=1, max_length=100)
    aud: str
    request_id: str = Field(min_length=1, max_length=100)
    exp: int = Field(strict=True)
    run_id: str = Field(default="", max_length=100)
    trace_id: str = Field(default="", max_length=100)


def mint(key: bytes, audience: str, context: CallContext) -> str:
    if len(key) < 32:
        raise ValueError("service_key_too_short")
    body = Claims(
        sub=context.subject_ref,
        action=context.action,
        scope=context.scope,
        aud=audience,
        request_id=context.request_id,
        exp=int(time()) + 30,
        run_id=context.run_id,
        trace_id=context.trace_id,
    )
    encoded = base64.urlsafe_b64encode(body.model_dump_json().encode()).decode().rstrip("=")
    signature = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def endpoint(settings: Settings, service: str) -> tuple[str, bytes] | None:
    routes = {
        "rag": (settings.rag_mcp_url, settings.rag_service_key),
        "ontology": (settings.ontology_mcp_url, settings.ontology_service_key),
    }
    value = routes.get(service)
    if value is None or not value[0]:
        return None
    url, secret = value
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("invalid_mcp_url")
    key = secret.get_secret_value().encode()
    if len(key) < 32:
        raise ValueError("service_key_too_short")
    return url, key


def grouped(labels: list[dict[str, str]]) -> dict[tuple[str, str, str], list[str]]:
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for label in labels:
        if "resource_ref" in label:
            groups[(label["service"], label["action"], label["scope"])].append(
                label["resource_ref"]
            )
    return groups


def batches(refs: list[str]) -> list[list[str]]:
    """Respect the service's per-request limit without dropping required evidence."""
    unique = list(dict.fromkeys(refs))
    return [unique[offset : offset + 20] for offset in range(0, len(unique), 20)]


def resource_access(settings: Settings, subject: str, labels: list[dict[str, str]]) -> bool:
    """Threaded HTTP API replay path; do not return cached ACL decisions."""
    if not grouped(labels):
        return True
    try:
        with httpx.Client(timeout=5) as client:
            for (service, action, scope), refs in grouped(labels).items():
                route = endpoint(settings, service)
                if not route:
                    return False
                url, key = route
                token = mint(key, service, CallContext(subject, action, scope, "replay", "", ""))
                for batch in batches(refs):
                    response = client.post(
                        url.removesuffix("/mcp") + "/access",
                        json={"delegation": token, "refs": batch},
                    )
                    if response.status_code != 200 or response.json() != {"allowed": True}:
                        return False
        return True
    except (httpx.HTTPError, ValueError, KeyError):
        return False


class MCPGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def call(self, call: ToolCall, context: CallContext) -> ToolResult:
        ToolRegistry().validate(call)
        service = call.tool.split(".")[0]
        route = endpoint(self.settings, service)
        if not route:
            return ToolResult(status="not_available", error_code="tool_not_connected")
        url, key = route
        # Validated model arguments cannot override the server-authenticated delegation.
        arguments: dict[str, Any] = {**call.arguments, "delegation": mint(key, service, context)}
        try:
            async with httpx.AsyncClient(timeout=self.settings.tool_timeout_seconds) as client:
                async with streamable_http_client(url, http_client=client) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        response = await session.call_tool(call.tool, arguments=arguments)
                        if response.isError:
                            raise ToolError("tool_failed")
                        body = response.structuredContent
                        if body is None:
                            raise ToolError("tool_failed")
                        result = ToolResult.model_validate(body["result"])
            return result
        except ValidationError:
            raise ToolError("tool_failed") from None
        except ToolError:
            raise
        except Exception:
            # ExceptionGroup/raw transport details are never exposed or retried implicitly.
            raise ToolError("tool_unavailable") from None

    async def authorize_evidence(self, subject: str, items: list[Evidence]) -> bool:
        labels = [
            {
                "service": "rag" if e.ref.startswith("rag:") else "ontology",
                "resource_ref": e.ref,
                "scope": e.scope,
                "action": "documents.read" if e.ref.startswith("rag:") else "inventory.read",
            }
            for e in items
        ]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                for (service, action, scope), refs in grouped(labels).items():
                    route = endpoint(self.settings, service)
                    if not route:
                        return False
                    url, key = route
                    token = mint(
                        key, service, CallContext(subject, action, scope, "verify", "", "")
                    )
                    for batch in batches(refs):
                        response = await client.post(
                            url.removesuffix("/mcp") + "/access",
                            json={"delegation": token, "refs": batch},
                        )
                        if response.status_code != 200 or response.json() != {"allowed": True}:
                            return False
            return True
        except (httpx.HTTPError, ValueError, KeyError):
            return False
