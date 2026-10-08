"""Private AGI HTTP API. Browser access is mediated by the same-origin BFF."""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from time import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modam.chat.database import Database, digest
from modam.chat.models import Cancellation, Conversation, Event, Run, SessionToken, User
from modam.chat.repository import (
    TERMINAL,
    Conflict,
    cancel,
    enqueue,
    owns,
    purge_conversation,
    run_data,
)
from modam.config import Settings
from modam.schemas import Contract


class Login(Contract):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class NewConversation(Contract):
    mode: Literal["general", "enterprise"] = "general"


class Submission(Contract):
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)
    cloud_allowed: bool = Field(strict=True)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Empty message")
        return value.strip()


class Policy(Contract):
    active: bool = Field(strict=True)
    cloud_allowed: bool = Field(strict=True)
    roles: list[Literal["admin", "user"]] = Field(max_length=2)
    grants: list[dict[str, str]] = Field(max_length=100)

    @field_validator("grants")
    @classmethod
    def valid_grants(cls, grants: list[dict[str, str]]) -> list[dict[str, str]]:
        for g in grants:
            if (
                set(g) != {"action", "scope"}
                or g["action"] not in {"documents.read", "inventory.read"}
                or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", g["scope"])
            ):
                raise ValueError("Invalid grant")
        return grants


class NewUser(Login):
    password: str = Field(min_length=12, max_length=256)


def visible(user: User, run: Run) -> bool:
    return all(any(g == label for g in user.grants) for label in run.evidence_labels)


def user_run_data(user: User, run: Run) -> dict[str, object]:
    data = run_data(run)
    if not visible(user, run):
        data["answer"] = "현재 조회 권한이 없습니다."
    return data


def create_app(database: Database | None = None) -> FastAPI:
    store = database or Database(Settings().database_url.get_secret_value())
    app = FastAPI(title="MODAM AGI chat", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def safe_errors(
        request: Request, next_handler: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await next_handler(request)
        except Exception:
            # Do not propagate DB parameters, user input or raw exception text to ASGI logs.
            return JSONResponse({"detail": "internal_error"}, status_code=503)

    def token(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or len(auth) > 256:
            raise HTTPException(401, "unauthenticated")
        return auth[7:]

    def identity(request: Request) -> User:
        with store.sessions() as db:
            user = store.authenticate(db, token(request))
            if not user:
                raise HTTPException(401, "unauthenticated")
            return user

    Current = Annotated[User, Depends(identity)]

    def owned_run(db_user: User, run_id: str) -> Run:
        with store.sessions() as db:
            run = db.get(Run, run_id)
            if not run or run.user_id != db_user.id:
                raise HTTPException(404, "not_found")
            return run

    @app.get("/health")
    def health() -> dict[str, str]:
        with store.sessions() as db:
            db.execute(select(1))
        return {"status": "ok"}

    @app.post("/v1/auth/login")
    def login(body: Login) -> dict[str, str]:
        value = store.login(body.username, body.password)
        if not value:
            raise HTTPException(401, "invalid_credentials")
        return {"token": value}

    @app.post("/v1/auth/logout", status_code=204)
    def logout(request: Request, user: Current) -> Response:
        with store.sessions.begin() as db:
            record = db.get(SessionToken, digest(token(request)))
            if record:
                db.delete(record)
        return Response(status_code=204)

    @app.get("/v1/session")
    def session(user: Current) -> dict[str, object]:
        return {
            "id": user.id,
            "username": user.username,
            "roles": user.roles,
            "cloud_allowed": user.cloud_allowed,
        }

    @app.post("/v1/conversations", status_code=201)
    def create(body: NewConversation, user: Current) -> dict[str, object]:
        with store.sessions.begin() as db:
            conversation = Conversation(
                id=str(uuid4()),
                user_id=user.id,
                mode=body.mode,
                title="새 대화",
                created=time(),
                updated=time(),
            )
            db.add(conversation)
            db.flush()
            return {"id": conversation.id, "title": conversation.title, "mode": conversation.mode}

    @app.get("/v1/conversations")
    def conversations(user: Current) -> list[dict[str, object]]:
        with store.sessions() as db:
            return [
                {"id": c.id, "title": c.title, "mode": c.mode}
                for c in db.scalars(
                    select(Conversation)
                    .where(Conversation.user_id == user.id)
                    .order_by(Conversation.updated.desc())
                    .limit(100)
                )
            ]

    @app.get("/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, user: Current) -> list[dict[str, object]]:
        with store.sessions() as db:
            if not owns(db, user.id, conversation_id):
                raise HTTPException(404, "not_found")
            result: list[dict[str, object]] = []
            for run in db.scalars(
                select(Run).where(Run.conversation_id == conversation_id).order_by(Run.created)
            ):
                result.append(
                    {
                        "id": run.id + "-user",
                        "role": "user",
                        "content": run.input,
                        "status": "complete",
                    }
                )
                result.append(
                    {
                        "id": run.id,
                        "role": "assistant",
                        "content": run.answer
                        if visible(user, run)
                        else "현재 조회 권한이 없습니다.",
                        "status": {
                            "queued": "streaming",
                            "running": "streaming",
                            "completed": "complete",
                            "failed": "error",
                            "cancelled": "cancelled",
                        }[run.status],
                        "run_id": run.id,
                    }
                )
            return result

    @app.delete("/v1/conversations/{conversation_id}", status_code=204)
    def remove(conversation_id: str, user: Current) -> Response:
        with store.sessions.begin() as db:
            conversation = owns(db, user.id, conversation_id, lock=True)
            if not conversation:
                raise HTTPException(404, "not_found")
            if db.scalar(
                select(Run.id).where(
                    Run.conversation_id == conversation.id, Run.status.in_(["queued", "running"])
                )
            ):
                raise HTTPException(409, "conversation_busy")
            purge_conversation(db, conversation)
        return Response(status_code=204)

    @app.post("/v1/conversations/{conversation_id}/runs", status_code=202)
    def submit(conversation_id: str, body: Submission, user: Current) -> dict[str, object]:
        try:
            with store.sessions.begin() as db:
                conversation = owns(db, user.id, conversation_id, lock=True)
                if not conversation:
                    raise HTTPException(404, "not_found")
                # Serialize per-user request IDs even across different conversations.
                current = db.scalar(select(User).where(User.id == user.id).with_for_update())
                if not current or not current.active:
                    raise HTTPException(401, "unauthenticated")
                return user_run_data(
                    current,
                    enqueue(
                        db, current, conversation, body.request_id, body.message, body.cloud_allowed
                    ),
                )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except IntegrityError:
            raise HTTPException(409, "concurrent_submission") from None

    @app.get("/v1/runs/{run_id}")
    def status(run_id: str, user: Current) -> dict[str, object]:
        run = owned_run(user, run_id)
        return user_run_data(user, run)

    @app.post("/v1/runs/{run_id}/cancel")
    def stop(run_id: str, user: Current) -> dict[str, object]:
        owned_run(user, run_id)
        with store.sessions.begin() as db:
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if not run:
                raise HTTPException(404, "not_found")
            cancel(db, run)
            return user_run_data(user, run)

    @app.post("/v1/requests/{request_id}/cancel", status_code=204)
    def stop_request(request_id: str, user: Current) -> Response:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", request_id):
            raise HTTPException(422, "invalid_request_id")
        with store.sessions.begin() as db:
            db.scalar(select(User).where(User.id == user.id).with_for_update())
            run = db.scalar(
                select(Run)
                .where(Run.user_id == user.id, Run.request_id == request_id)
                .with_for_update()
            )
            if run:
                cancel(db, run)
            elif not db.scalar(
                select(Cancellation.id).where(
                    Cancellation.user_id == user.id, Cancellation.request_id == request_id
                )
            ):
                db.add(
                    Cancellation(
                        id=str(uuid4()), user_id=user.id, request_id=request_id, created=time()
                    )
                )
        return Response(status_code=204)

    @app.get("/v1/runs/{run_id}/events")
    async def events(
        run_id: str, request: Request, user: Current, after: int = 0
    ) -> StreamingResponse:
        owned_run(user, run_id)
        if after < 0:
            raise HTTPException(422, "invalid_cursor")
        header = request.headers.get("last-event-id", "0")
        try:
            cursor = max(after, int(header))
        except ValueError:
            raise HTTPException(422, "invalid_cursor") from None

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            for _ in range(120):
                if await request.is_disconnected():
                    return
                with store.sessions() as db:
                    current = store.authenticate(db, token(request))
                    run = db.get(Run, run_id)
                    if not current or not run:
                        return
                    batch = list(
                        db.scalars(
                            select(Event)
                            .where(Event.run_id == run_id, Event.id > cursor)
                            .order_by(Event.id)
                            .limit(100)
                        )
                    )
                    terminal = run.status in TERMINAL
                    for item in batch:
                        data = dict(item.data)
                        if not visible(current, run):
                            data["answer"] = "현재 조회 권한이 없습니다."
                        cursor = item.id
                        payload = json.dumps(data, ensure_ascii=False)
                        yield f"id: {item.id}\nevent: {item.kind}\ndata: {payload}\n\n"
                if terminal:
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/admin/users")
    def users(user: Current) -> list[dict[str, object]]:
        if "admin" not in user.roles:
            raise HTTPException(403, "admin_required")
        with store.sessions() as db:
            return [
                {
                    "id": u.id,
                    "username": u.username,
                    "roles": u.roles,
                    "grants": u.grants,
                    "active": u.active,
                    "cloud_allowed": u.cloud_allowed,
                }
                for u in db.scalars(select(User).limit(1000))
            ]

    @app.post("/v1/admin/users", status_code=201)
    def add_user(body: NewUser, user: Current) -> dict[str, str]:
        if "admin" not in user.roles:
            raise HTTPException(403, "admin_required")
        try:
            return {"id": store.create_user(body.username, body.password)}
        except IntegrityError:
            raise HTTPException(409, "username_exists") from None

    @app.put("/v1/admin/users/{user_id}/policy", status_code=204)
    def policy(user_id: str, body: Policy, user: Current) -> Response:
        if "admin" not in user.roles:
            raise HTTPException(403, "admin_required")
        if user_id == user.id and (not body.active or "admin" not in body.roles):
            raise HTTPException(409, "cannot_remove_own_admin")
        with store.sessions.begin() as db:
            target = db.get(User, user_id)
            if not target:
                raise HTTPException(404, "not_found")
            target.active, target.cloud_allowed = body.active, body.cloud_allowed
            target.roles, target.grants = list(body.roles), body.grants
        return Response(status_code=204)

    return app
