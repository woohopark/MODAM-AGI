# MODAM-AGI 구현 상태

2026-10-08 · 현재 v0.4.0. 최신 구현과 검증은 아래 지식 서비스 연결을 따른다.

## 독립 RAG/ONTOLOGY 실제 연결 · v0.4.0

공식 MCP Gateway + 서비스별 짧은 HMAC 위임 + private 현재 권한 introspection을 구현했다.
도구 스키마는 기존 허용 catalog를 유지한다. 저장된 답변은 현재 scope grant와 원천 근거 ACL/
버전을 다시 검사하여 회수·삭제·갱신 시 숨긴다. 자료 저장소는 각 서비스가 소유한다.
답변에는 근거 ref/버전/시점을 표시한다. 관리자 역할에 기업 grant를 자동 추가하지 않았다.

이번 검사: AGI 44개 + 실제 HTTP/MCP 통합 2개, RAG 17개, ONTOLOGY 19개,
CHAT 74개. Ruff/format/mypy/frozen uv/wheel, CHAT npm run check 통과.
실제 Compose/Groq 기업 조회 3턴(6메시지), 규정+객체 결합/경로 인용, 서비스 재시작 영속 복원,
문서 ACL 회수 시 과거 답변 숨김을 검사했다. Chromium 다크/기업 이력·인용 복원도 검사했다.
후속 제한과 실행 명령은 [지식 서비스 통합](docs/KNOWLEDGE_INTEGRATION.md)을 따른다.
이 절의 새 MCP 검증은 앞선 미연결 검증 당시와 구분한다. 외부 URL은 아직 없다.

## 이전 v0.3.0 CHAT 구현/검증 기록


2026-10-08 · v0.3.0 · 사용자 승인된 MODAM-CHAT 네트워크/멀티턴 구축.

## 구현된 기능

- 기존 Groq-only 기업 읽기 Engine, 현재 신원/권한/Cloud 정책, 제한된 계획/도구/근거 검증·관측·14개 고정 평가 유지.
- FastAPI 인증/세션/소유 대화/실행/취소/SSE/삭제 API; Argon2id PW, opaque session digest, admin/user 복수 Role와 정확한 action/scope grant 관리.
- PostgreSQL + SQLAlchemy + immutable Alembic migration. 영속 대화·작업·이벤트·생성 전 취소. 사용자별 request_id 멱등성과 대화당 활성 실행 unique index.
- 별도 worker와 SKIP LOCKED claim/lease. 단절은 실행 유지, 명시적 취소는 task 중단, 장애 후 만료 실행은 worker_lost로 종료하여 자동 모델 중복 호출 방지.
- 일반 Groq 대화/기업 조회 분리. canonical 완료 10턴/20,000 code point, 실패/취소 제외, 과거 기업 답변 원문 재전송 금지·표시 시 현재 grant 재검사.
- MODAM-CHAT Fastify BFF와 실제 브라우저 연동. HttpOnly/SameSite cookie, production Secure/HTTPS origin 검사, 로그인 rate limit, typed provider events와 복원/삭제 repository.
- Docker Compose: private PostgreSQL/API/worker, BFF loopback 3300. 키는 worker env에만 주입. 데이터를 보존하는 DB volume.

## 이번 검증

- AGI Ruff lint/format·mypy strict·36개 pytest 통과, uv sync --frozen 및 v0.3.0 wheel/sdist 빌드.
- 합성 경계 평가 14개 × 3회 = 42개 통과, 별도 워밍업 1회. 실제 LLM 성능/실제 MCP 통과로 집계하지 않는다.
- CHAT 포맷/린트/strict/73개 테스트/클라이언트·BFF 빌드 통과. 핵심 경계+BFF coverage statements 95.89%, branches 95.04%, functions 90%, lines 96.85%. npm audit --omit=dev 취약점 0건(실행 시점).
- 실제 native PostgreSQL + BFF + API + 별도 worker + Groq 3턴, 6메시지 복원·SSE·중복 ID 재전송·HttpOnly 확인.
- 실제 Docker 전 스택 Groq 3턴 통과. BFF/API/worker 프로세스 재시작 후 session/history 유지와 다음 턴 context 통과. 생성 전/후 취소·현재 소유권·다른 사용자 404·일반 사용자 admin 403 확인.
- 실제 기업 Groq 계획 + 현재 logistics documents.read grant 검사 후 MCP 미연결이 not_available/tool_not_connected로 반환되는 것을 확인.
- Chromium 실제 HTTP 로그인·2턴 Groq·새로고침 복원·다크 CSS·모바일 sidebar·합성 composition event 확인. 물리 키보드 IME·200% 확대·전체 색상 대비 검사는 별도 미검증.

실제 검증 보고서는 Git 제외 .local/reports에 있다. 테스트 대역 결과와 실제 Groq/PostgreSQL/브라우저 결과를 구분한다. 상세 [CHAT 계약](docs/CHAT_INTEGRATION.md) / [실행·배포](docs/CHAT_DEPLOYMENT.md).

## 실행/외부 배포

workspace 내부 native BFF http://127.0.0.1:3000, Docker BFF http://127.0.0.1:3300. 사용자 PC의 localhost가 아니므로 외부 공개 주소로 안내하지 않는다. 기존 Sites 주소는 소유자 제한 정적 데모로 유지한다. 현재 운영 서버 자격증명·도메인·포트 공개 연결이 없어 외부 실제 AGI URL은 미발급이다.

## 후속 및 제한

실제 RAG/ONTOLOGY MCP·서명 위임·승인/알림/ERP 변경 도구, 임의 Role 정의/Role grant 템플릿, 운영 DB 백업/암호화·동시 부하·SLO·외부 운영 배포는 후속이다. Admin은 기업 실행 grant를 자동 상속하지 않는다. 전체 PRD/범용 AGI 완성을 주장하지 않는다.

이전 foundation 검증과 기준점은 docs/FOUNDATION_REVIEW.md, docs/legacy와 baseline-monolith-cadea94 Git tag에 보존한다. 신규 chat DB/volume만 생성했으며 기존 DB/volume은 삭제하지 않았다.

## 로컬 PC 실행 보완

일반 PC용 compose.local.yaml과 표준 라이브러리 setup/start/account/status/stop 명령을 추가했다. CA secret은 별도 신뢰 저장소가 필요한 환경에서 선택 제공하며 일반 PC는 컨테이너 기본 CA를 사용한다. TLS 검증을 유지한다. 설정은 랜덤 DB 비밀번호/키를 로컬에 생성하며 기존 값을 덮지 않는다. [PC 안내](docs/LOCAL_PC.md)를 따른다.

이번 보완 검증: AGI 37개 테스트·Ruff/mypy·wheel, CHAT 73개·npm run check 통과. 일반 PC compose를 이 Linux 환경의 CA override와 함께 빌드/실행하여 API/BFF/DB health 및 migration 완료를 확인했다. Windows/macOS 실기기 검증은 미수행이다.

일반 PC compose 기반 서비스에서 실제 Groq 3턴·SSE·대화 저장/복원도 통과했다(.local/reports/local-compose-live.json).
