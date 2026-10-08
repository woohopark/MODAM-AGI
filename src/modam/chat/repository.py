"""Canonical history, serialized submission, cancellation and replayable events."""

import hashlib
import json
from time import time
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from modam.chat.models import Cancellation, Conversation, Event, Run, User

TERMINAL = {"completed", "failed", "cancelled"}


class Conflict(Exception):
    pass


def run_data(run: Run) -> dict[str, object]:
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "request_id": run.request_id,
        "status": run.status,
        "outcome": run.outcome,
        "answer": run.answer,
        "error_code": run.error_code,
    }


def event(db: Session, run: Run, kind: str) -> None:
    db.add(Event(run_id=run.id, kind=kind, data=run_data(run)))


def owns(
    db: Session, user_id: str, conversation_id: str, *, lock: bool = False
) -> Conversation | None:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def enqueue(
    db: Session,
    user: User,
    conversation: Conversation,
    request_id: str,
    message: str,
    cloud_allowed: bool,
) -> Run:
    fingerprint = hashlib.sha256(
        json.dumps([conversation.id, message, cloud_allowed], ensure_ascii=False).encode()
    ).hexdigest()
    existing = db.scalar(select(Run).where(Run.user_id == user.id, Run.request_id == request_id))
    if existing:
        if existing.fingerprint != fingerprint:
            raise Conflict("request_id_conflict")
        return existing
    if db.scalar(
        select(Run.id).where(
            Run.conversation_id == conversation.id, Run.status.in_(["queued", "running"])
        )
    ):
        raise Conflict("conversation_busy")
    if not cloud_allowed or not user.cloud_allowed:
        raise Conflict("cloud_transmission_not_allowed")
    cancelled = db.scalar(
        select(Cancellation.id).where(
            Cancellation.user_id == user.id, Cancellation.request_id == request_id
        )
    )
    run = Run(
        id=str(uuid4()),
        user_id=user.id,
        conversation_id=conversation.id,
        request_id=request_id,
        fingerprint=fingerprint,
        input=message,
        status="cancelled" if cancelled else "queued",
        created=time(),
        answer="",
        evidence_labels=[],
        finished=time() if cancelled else None,
    )
    db.add(run)
    db.flush()
    conversation.updated = time()
    if conversation.title == "새 대화":
        conversation.title = message[:32]
    event(db, run, "cancelled" if cancelled else "accepted")
    return run


def cancel(db: Session, run: Run) -> None:
    if run.status not in TERMINAL:
        run.status, run.finished = "cancelled", time()
        run.answer = ""
        event(db, run, "cancelled")


def history(db: Session, conversation_id: str) -> list[dict[str, str]]:
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.conversation_id == conversation_id, Run.status == "completed")
            .order_by(Run.created.desc())
            .limit(10)
        )
    )[::-1]
    messages: list[dict[str, str]] = []
    budget = 20000
    for run in reversed(runs):
        # Enterprise answers are not reused as fresh evidence. Clarification is safe context.
        answer = (
            run.answer if not run.evidence_labels else "[과거 기업 조회: 현재 데이터 재조회 필요]"
        )
        size = len(run.input) + len(answer)
        if size > budget:
            break
        budget -= size
        messages[0:0] = [
            {"role": "user", "content": run.input},
            {"role": "assistant", "content": answer},
        ]
    return messages


def purge_conversation(db: Session, conversation: Conversation) -> None:
    ids = select(Run.id).where(Run.conversation_id == conversation.id)
    db.execute(delete(Event).where(Event.run_id.in_(ids)))
    db.execute(delete(Run).where(Run.conversation_id == conversation.id))
    db.delete(conversation)
