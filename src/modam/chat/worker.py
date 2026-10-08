"""Independent durable worker. Expired running jobs fail safely; never auto-repeat Groq."""

import asyncio
from time import time
from uuid import uuid4

from sqlalchemy import delete, select

from modam.chat.database import Database, DatabaseAuthority
from modam.chat.models import Cancellation, Conversation, Run, SessionToken
from modam.chat.repository import event, history, purge_conversation
from modam.config import Settings
from modam.engine import Engine
from modam.llm import GroqModel, ModelError
from modam.observability import Observer
from modam.schemas import Request
from modam.tools import DisconnectedGateway, ToolRegistry


class Worker:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database, self.settings = database, settings
        self.id = str(uuid4())

    def recover(self) -> int:
        count = 0
        with self.database.sessions.begin() as db:
            for run in db.scalars(
                select(Run)
                .where(Run.status == "running", Run.lease_until < time())
                .with_for_update(skip_locked=True)
            ):
                run.status, run.error_code, run.finished = "failed", "worker_lost", time()
                run.answer = (
                    "실행 중 서버가 종료되어 결과를 확인할 수 없습니다. 다시 요청해 주세요."
                )
                event(db, run, "error")
                count += 1
        return count

    def cleanup(self) -> None:
        with self.database.sessions.begin() as db:
            db.execute(delete(SessionToken).where(SessionToken.expires < time()))
            db.execute(delete(Cancellation).where(Cancellation.created < time() - 86400))
            for c in db.scalars(
                select(Conversation)
                .where(Conversation.updated < time() - 30 * 86400)
                .with_for_update(skip_locked=True)
            ):
                if not db.scalar(
                    select(Run.id).where(
                        Run.conversation_id == c.id, Run.status.in_(["queued", "running"])
                    )
                ):
                    purge_conversation(db, c)

    def claim(self) -> str | None:
        with self.database.sessions.begin() as db:
            run = db.scalar(
                select(Run)
                .where(Run.status == "queued")
                .order_by(Run.created)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not run:
                return None
            run.status, run.worker_id = "running", self.id
            run.lease_until = time() + self.settings.run_timeout_seconds + 30
            event(db, run, "status")
            return run.id

    async def execute(self, run_id: str) -> None:
        with self.database.sessions() as db:
            run = db.get(Run, run_id)
            if not run or run.status != "running" or run.worker_id != self.id:
                return
            conversation = db.get(Conversation, run.conversation_id)
            if not conversation:
                return
            prior = history(db, conversation.id)
            mode, subject, request_id, message = (
                conversation.mode,
                run.user_id,
                run.request_id,
                run.input,
            )
        authority = DatabaseAuthority(self.database)
        model = GroqModel(self.settings, history=prior)
        observer = Observer()

        async def generate() -> tuple[str, str, str | None, list[dict[str, str]]]:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                if not await authority.is_active(subject) or not await authority.can_send(
                    subject, None
                ):
                    return (
                        "denied",
                        "요청을 진행할 권한 또는 전송 허용이 없습니다.",
                        "permission_denied",
                        [],
                    )
                if mode == "general":
                    return "completed", await model.chat(message), None, []
                result = await Engine(
                    model, DisconnectedGateway(), authority, ToolRegistry(), observer, self.settings
                ).run(
                    Request(
                        request_id=request_id,
                        subject_ref=subject,
                        message=message,
                        cloud_allowed=True,
                    )
                )
                # Preserve policy labels for reauthorization of past displayed answers.
                labels = (
                    [
                        {"action": grant.action, "scope": scope}
                        for grant in result.grants_used
                        for scope in grant.scopes
                    ]
                    if result.evidence
                    else []
                )
                return result.status, result.message, result.error_code, labels

        task = asyncio.create_task(generate())
        try:
            while not task.done():
                await asyncio.sleep(0.2)
                with self.database.sessions() as db:
                    current = db.get(Run, run_id)
                    if not current or current.status != "running" or current.worker_id != self.id:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        return
            outcome, answer, code, labels = await task
            if not await authority.is_active(subject) or not await authority.can_send(
                subject, None
            ):
                outcome, answer, code, labels = (
                    "denied",
                    "현재 전송 권한이 없습니다.",
                    "permission_denied",
                    [],
                )
            for label in labels:
                if not await authority.permits(subject, label["action"], label["scope"]):
                    outcome, answer, code, labels = (
                        "denied",
                        "현재 조회 권한이 없습니다.",
                        "permission_denied",
                        [],
                    )
                    break
            self.finish(run_id, outcome, answer, code, labels)
        except (ModelError, TimeoutError) as exc:
            self.finish(
                run_id,
                "failed",
                "응답을 불러오지 못했습니다. 다시 요청해 주세요.",
                exc.code if isinstance(exc, ModelError) else "run_timeout",
                [],
            )
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        except Exception:
            self.finish(run_id, "failed", "요청 처리에 실패했습니다.", "internal_error", [])
        finally:
            await model.close()
            observer.close()

    def finish(
        self, run_id: str, outcome: str, answer: str, code: str | None, labels: list[dict[str, str]]
    ) -> None:
        with self.database.sessions.begin() as db:
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if not run or run.status != "running" or run.worker_id != self.id:
                return
            run.status = (
                "failed"
                if outcome in {"failed", "denied", "unknown", "not_available"}
                else "completed"
            )
            run.outcome, run.answer, run.error_code = outcome, answer, code
            run.finished, run.evidence_labels = time(), labels
            event(db, run, "message")
            event(db, run, "error" if run.status == "failed" else "done")

    async def serve(self) -> None:
        last_cleanup = 0.0
        while True:
            try:
                self.recover()
                if time() - last_cleanup > 3600:
                    self.cleanup()
                    last_cleanup = time()
                run_id = self.claim()
                if run_id:
                    await self.execute(run_id)
                else:
                    await asyncio.sleep(0.3)
            except Exception:
                print('{"event":"worker.database_unavailable"}', flush=True)
                await asyncio.sleep(3)


def main() -> None:
    settings = Settings()
    asyncio.run(Worker(Database(settings.database_url.get_secret_value()), settings).serve())
