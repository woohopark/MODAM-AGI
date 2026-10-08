import time
from collections.abc import Generator
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, and_, or_, select, true, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from modam.agent import interpret_and_authorize
from modam.business import run_tool, snapshot_parameters
from modam.config import Settings
from modam.db import make_engine, session_factory
from modam.llm import GroqInterpreter, Interpreter, ModelError, model_calls, reset_model_calls
from modam.models import Approval, Audit, ChatRun, Conversation, Role, User, now
from modam.schemas import (
    ApprovalCreate,
    ApprovalView,
    AuditView,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    Decision,
    Grant,
    Intent,
    Login,
    PermissionCheck,
    RoleCreate,
    RoleView,
    TokenView,
    UserCreate,
    UserPatch,
    UserView,
)
from modam.security import (
    allowed,
    audit,
    has_action,
    hash_password,
    issue_session,
    session_user,
    token_hash,
    verify_password,
)

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = cast(sessionmaker[Session], request.app.state.sessions)
    with factory() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def current_user(db: DB, credentials: Credentials) -> User:
    user = session_user(db, credentials.credentials) if credentials else None
    if user is None:
        raise HTTPException(401, "authentication_required", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(db: Session, user: User, action: str, scope: str | None) -> None:
    if not allowed(user, action, scope):
        audit(db, user, "permission.check", "denied", {"action": action})
        db.commit()
        raise HTTPException(403, "permission_denied")


def admin_user(db: DB, user: CurrentUser) -> User:
    require(db, user, "admin.manage", "*")
    return user


Admin = Annotated[User, Depends(admin_user)]


def role_view(role: Role) -> RoleView:
    return RoleView(
        id=role.id, name=role.name, grants=[Grant.model_validate(g) for g in role.grants]
    )


def user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        username=user.username,
        active=user.active,
        roles=[role_view(role) for role in user.roles],
    )


def approval_view(row: Approval) -> ApprovalView:
    return ApprovalView.model_validate(row, from_attributes=True)


def resolve_roles(db: Session, ids: list[str]) -> list[Role]:
    roles = list(db.scalars(select(Role).where(Role.id.in_(ids))))
    if {role.id for role in roles} != set(ids):
        raise HTTPException(422, "unknown_role")
    return roles


def create_app(
    settings: Settings | None = None,
    interpreter: Interpreter | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    config = settings or Settings()
    app = FastAPI(title="MODAM-AGI", version="0.1.0")
    app.state.settings = config
    app.state.engine = engine or make_engine(config.database_url)
    app.state.sessions = session_factory(app.state.engine)
    app.state.interpreter = interpreter or GroqInterpreter(config)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready(db: DB) -> dict[str, str]:
        try:
            db.execute(select(User.id).limit(1))
        except SQLAlchemyError:
            raise HTTPException(503, "database_not_ready") from None
        return {"status": "ready"}

    @app.post("/v1/auth/login", response_model=TokenView)
    def login(payload: Login, db: DB) -> TokenView:
        user = db.scalar(select(User).where(User.username == payload.username))
        verified = verify_password(user.password_hash if user else None, payload.password)
        if user is None or not verified or not user.active:
            audit(db, None, "auth.login", "denied")
            db.commit()
            raise HTTPException(401, "invalid_credentials")
        token, row = issue_session(db, user, config.session_ttl_seconds)
        audit(db, user, "auth.login", "authenticated")
        db.commit()
        return TokenView(token=token, expires_at=row.expires_at)

    @app.post("/v1/auth/logout", status_code=204)
    def logout(db: DB, user: CurrentUser, credentials: Credentials) -> None:
        from modam.models import AuthSession

        if credentials:
            row = db.get(AuthSession, token_hash(credentials.credentials))
            if row:
                db.delete(row)
        audit(db, user, "auth.logout", "revoked")
        db.commit()

    @app.get("/v1/auth/me", response_model=UserView)
    def me(user: CurrentUser) -> UserView:
        return user_view(user)

    @app.post("/v1/admin/roles", response_model=RoleView, status_code=201)
    def create_role(payload: RoleCreate, db: DB, admin: Admin) -> RoleView:
        row = Role(name=payload.name, grants=[grant.model_dump() for grant in payload.grants])
        db.add(row)
        try:
            db.flush()
            audit(db, admin, "role.create", "created", {"role_id": row.id})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "role_exists") from None
        return role_view(row)

    @app.get("/v1/admin/roles", response_model=list[RoleView])
    def roles(db: DB, admin: Admin) -> list[RoleView]:
        return [role_view(role) for role in db.scalars(select(Role).order_by(Role.name))]

    @app.post("/v1/admin/users", response_model=UserView, status_code=201)
    def create_user(payload: UserCreate, db: DB, admin: Admin) -> UserView:
        user = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            roles=resolve_roles(db, payload.role_ids),
        )
        db.add(user)
        try:
            db.flush()
            audit(db, admin, "user.create", "created", {"target_user_id": user.id})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "user_exists") from None
        return user_view(user)

    @app.get("/v1/admin/users", response_model=list[UserView])
    def users(db: DB, admin: Admin) -> list[UserView]:
        return [user_view(user) for user in db.scalars(select(User).order_by(User.username))]

    @app.patch("/v1/admin/users/{user_id}", response_model=UserView)
    def patch_user(user_id: str, payload: UserPatch, db: DB, admin: Admin) -> UserView:
        # Serialize admin changes so two concurrent removals cannot remove the last admin.
        db.expire_all()
        all_users = list(db.scalars(select(User).order_by(User.id).with_for_update()))
        require(db, admin, "admin.manage", "*")
        user = next((candidate for candidate in all_users if candidate.id == user_id), None)
        if user is None:
            raise HTTPException(404, "user_not_found")
        if payload.role_ids is not None:
            user.roles = resolve_roles(db, payload.role_ids)
        if payload.active is not None:
            user.active = payload.active
        if not any(allowed(candidate, "admin.manage", "*") for candidate in all_users):
            db.rollback()
            raise HTTPException(409, "last_active_admin")
        audit(db, admin, "user.update", "updated", {"target_user_id": user.id})
        db.commit()
        return user_view(user)

    @app.post("/v1/permissions/check")
    def check_permission(payload: PermissionCheck, db: DB, user: CurrentUser) -> dict[str, bool]:
        result = allowed(user, payload.action, payload.scope)
        audit(db, user, "permission.check", "allowed" if result else "denied", payload.model_dump())
        db.commit()
        return {"allowed": result}

    @app.post("/v1/approvals", response_model=ApprovalView, status_code=201)
    def create_approval(payload: ApprovalCreate, db: DB, user: CurrentUser) -> ApprovalView:
        require(db, user, payload.action, payload.scope)

        def existing() -> Approval | None:
            return db.scalar(
                select(Approval).where(
                    Approval.requester_id == user.id, Approval.request_key == payload.request_key
                )
            )

        def verify_existing(row: Approval) -> ApprovalView:
            if (
                row.action != payload.action
                or row.scope != payload.scope
                or {k: v for k, v in row.parameters.items() if k != "expected_revision"}
                != payload.parameters.model_dump(exclude={"expected_revision"})
                or (
                    payload.parameters.expected_revision is not None
                    and row.parameters.get("expected_revision")
                    != payload.parameters.expected_revision
                )
            ):
                raise HTTPException(409, "idempotency_conflict")
            return approval_view(row)

        previous = existing()
        if previous:
            return verify_existing(previous)
        row = Approval(
            requester_id=user.id,
            request_key=payload.request_key,
            action=payload.action,
            scope=payload.scope,
            parameters=snapshot_parameters(db, payload.scope, payload.parameters.model_dump()),
        )
        db.add(row)
        try:
            db.flush()
            audit(db, user, "approval.create", "pending", {"approval_id": row.id})
            db.commit()
        except IntegrityError:
            db.rollback()
            previous = existing()
            if previous is None:
                raise HTTPException(409, "request_conflict") from None
            return verify_existing(previous)
        return approval_view(row)

    @app.get("/v1/approvals", response_model=list[ApprovalView])
    def approvals(db: DB, user: CurrentUser) -> list[ApprovalView]:
        def scopes_for(action: str) -> set[str]:
            return {
                scope
                for role in user.roles
                for grant in role.grants
                if grant["action"] == action
                for scope in grant["scopes"]
            }

        proposer_scopes = scopes_for("procurement.propose")
        approver_scopes = scopes_for("procurement.approve")
        query = (
            select(Approval)
            .where(
                or_(
                    and_(
                        Approval.requester_id == user.id,
                        true() if "*" in proposer_scopes else Approval.scope.in_(proposer_scopes),
                    ),
                    true() if "*" in approver_scopes else Approval.scope.in_(approver_scopes),
                )
            )
            .order_by(Approval.created_at.desc())
            .limit(500)
        )
        return [approval_view(row) for row in db.scalars(query)]

    @app.post("/v1/approvals/{approval_id}/decision", response_model=ApprovalView)
    def decide(approval_id: str, payload: Decision, db: DB, user: CurrentUser) -> ApprovalView:
        row = db.get(Approval, approval_id)
        if row is None or not allowed(user, "procurement.approve", row.scope):
            raise HTTPException(404, "approval_not_found")
        requester = db.get(User, row.requester_id)
        if requester is None or not allowed(requester, row.action, row.scope):
            raise HTTPException(409, "requester_permission_changed")
        if row.status != "pending":
            if row.status == payload.decision and row.approver_id == user.id:
                return approval_view(row)
            raise HTTPException(409, "approval_already_decided")
        changed = db.execute(
            update(Approval)
            .where(Approval.id == row.id, Approval.status == "pending")
            .values(status=payload.decision, approver_id=user.id, decided_at=now())
        )
        if changed.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise HTTPException(409, "approval_already_decided")
        audit(db, user, "approval.decision", payload.decision, {"approval_id": row.id})
        db.commit()
        db.refresh(row)
        return approval_view(row)

    @app.get("/v1/admin/audit", response_model=list[AuditView])
    def audits(db: DB, admin: Admin, limit: int = 100) -> list[AuditView]:
        if not 1 <= limit <= 500:
            raise HTTPException(422, "invalid_limit")
        rows = db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(limit))
        return [AuditView.model_validate(row, from_attributes=True) for row in rows]

    @app.get("/v1/admin/model")
    def model_status(admin: Admin) -> dict[str, object]:
        return {
            "provider": "groq",
            "model": config.groq_model,
            "key_configured": bool(config.groq_api_key.get_secret_value()),
            "application": "restart_required_for_environment_changes",
        }

    @app.post("/v1/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, db: DB, user: CurrentUser) -> ChatResponse:
        interpreter_instance = cast(Interpreter, app.state.interpreter)
        if interpreter_instance.provider != "recorded-fixture" and not payload.cloud_allowed:
            audit(db, user, "chat.cloud", "denied", request_id=payload.request_id)
            db.commit()
            raise HTTPException(403, "cloud_transmission_not_allowed")
        previous = db.scalar(
            select(ChatRun).where(
                ChatRun.user_id == user.id, ChatRun.request_id == payload.request_id
            )
        )
        if previous:
            if previous.message != payload.message or (
                payload.conversation_id and previous.conversation_id != payload.conversation_id
            ):
                raise HTTPException(409, "idempotency_conflict")
            if previous.response is None:
                raise HTTPException(409, "request_in_progress")
            result = ChatResponse.model_validate(previous.response)
            # Do not release historic parsed targets after permission revocation.
            if result.intent and result.intent.action != "unsupported":
                if not (
                    allowed(user, result.intent.action, result.intent.scope)
                    if result.intent.scope is not None
                    else has_action(user, result.intent.action)
                ):
                    result.status = "denied"
                    result.message = "현재 해당 업무 대상에 접근할 권한이 없습니다."
                    result.intent = None
                    result.data = {}
                    result.evidence = []
            return result
        if payload.conversation_id:
            conversation = db.get(Conversation, payload.conversation_id)
            if conversation is None or conversation.user_id != user.id:
                raise HTTPException(404, "conversation_not_found")
        else:
            conversation = Conversation(user_id=user.id)
            db.add(conversation)
            db.flush()
        # Only user-supplied, explicitly Cloud-consented messages form the context.
        history = list(
            db.scalars(
                select(ChatRun.message)
                .where(ChatRun.conversation_id == conversation.id, ChatRun.status != "processing")
                .order_by(ChatRun.created_at.desc())
                .limit(6)
            )
        )[::-1]
        row = ChatRun(
            user_id=user.id,
            conversation_id=conversation.id,
            request_id=payload.request_id,
            message=payload.message,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "request_conflict") from None
        interpreter_instance = cast(Interpreter, app.state.interpreter)
        started = time.monotonic()
        user_id = user.id

        def reload_user() -> User:
            db.expire_all()
            current = db.get(User, user_id)
            if current is None:
                raise ModelError("user_unavailable")
            return current

        reset_model_calls()
        try:
            state = interpret_and_authorize(
                interpreter_instance,
                reload_user,
                payload.message,
                history,
                lambda intent: run_tool(
                    db,
                    reload_user(),
                    interpreter_instance,
                    intent,
                    payload.message,
                    payload.request_id,
                ),
            )
            result = ChatResponse(
                request_id=payload.request_id,
                conversation_id=conversation.id,
                status=cast(ChatStatus, state["status"]),
                message=state["reply"],
                intent=Intent.model_validate(state["intent"]),
                provider=interpreter_instance.provider,
                model=interpreter_instance.model,
                data=state.get("data", {}),
                evidence=state.get("evidence", []),
                timings_ms=state.get("timings_ms", {}),
            )
            if result.intent and result.intent.action != "unsupported":
                current = reload_user()
                if not (
                    allowed(current, result.intent.action, result.intent.scope)
                    if result.intent.scope is not None
                    else has_action(current, result.intent.action)
                ):
                    result.status = "denied"
                    result.message = "현재 해당 업무 대상에 접근할 권한이 없습니다."
            if result.status == "denied":
                result.intent = None
                result.data = {}
                result.evidence = []
        except (ModelError, HTTPException) as exc:
            db.rollback()
            code = exc.code if isinstance(exc, ModelError) else str(exc.detail)
            result = ChatResponse(
                request_id=payload.request_id,
                conversation_id=conversation.id,
                status="failed",
                message="모델 요청을 처리하지 못했습니다. 업무는 실행하지 않았습니다.",
                error_code=code,
                provider=interpreter_instance.provider,
                model=interpreter_instance.model,
            )
        result.model_calls = model_calls()
        row.status = result.status
        row.response = result.model_dump(mode="json")
        audit(
            db,
            user,
            "chat.authorize",
            result.status,
            {
                "provider": result.provider,
                "model": result.model,
                "action": result.intent.action if result.intent else None,
                "error_code": result.error_code,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "steps": ["interpret", "authorize", "tools"],
                "timings_ms": result.timings_ms,
                "model_calls": result.model_calls,
            },
            payload.request_id,
        )
        db.commit()
        return result

    from modam.business_api import router

    app.include_router(router)
    return app
