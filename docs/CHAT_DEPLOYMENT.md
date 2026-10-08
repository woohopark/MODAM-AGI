# MODAM 채팅 실행·배포

2026-10-08. 실제 연동 실행은 Node Fastify BFF + FastAPI + 별도 워커 + PostgreSQL이다.

## 사용자 PC의 로컬 실행

운영 서버 없이 [로컬 PC 안내](LOCAL_PC.md)에 따라 실제 서비스를 실행할 수 있다. 일반 PC용 `deployment/compose.local.yaml`은 클라우드 인증서 경로를 요구하지 않는다.

## 이 workspace에서 실행 중인 환경

- 프론트/BFF: `http://127.0.0.1:3000` (workspace 내부).
- AGI: `http://127.0.0.1:8000`, PostgreSQL: loopback 5432. 브라우저는 AGI에 직접 요청하지 않는다.
- Docker 전체 스택: 검증 후 `http://127.0.0.1:3300`. 외부 운영 배포와 구분한다.
- 최초 관리자 username/password: `/workspace/modam-agi/.local/chat-runtime.json`의 보호된 로컬 파일(0600). Git/브라우저 JS/로그에 비밀번호를 넣지 않는다. 계정을 다른 환경에 옮길 때는 그 환경에서 명시적으로 새로 만든다.
- Groq 키는 AGI `.local/groq.env`(0600). `.local/with-runtime`은 키·DB URL을 자식 프로세스의 환경변수로만 주입한다. 새 채팅 workspace에 파일·실행 프로세스가 자동 공유된다고 가정하지 않는다.

## 개발 실행

AGI에서 안전하게 환경변수 `MODAM_DATABASE_URL`, `GROQ_API_KEY`를 주입하고:

```bash
uv sync --frozen
uv run alembic upgrade head
uv run modam-create-user your-id --admin
uv run modam-api
# 별도 터미널, 동일 DB와 Groq 환경
uv run modam-worker
```

이 workspace의 보안 주입기를 사용할 때는 각 명령 앞에 `.local/with-runtime`을 붙인다. migration은 저장소의 migrations/와 alembic.ini를 사용한다; wheel 단독에는 운영 migration 폴더가 포함되지 않는다.

CHAT에서:

```bash
npm ci
npm run build
npm run server
# 개발 HMR: BFF는 npm run server:dev, 다른 터미널에서 npm run dev
```

Vite 5173은 `/api`를 BFF 3000으로 proxy한다. production은 빌드된 서버를 Node로 실행하며 tsx/TypeScript/Vite는 운영 의존성이 아니다. 정적 데모만 필요하면 `VITE_CHAT_MODE=demo npm run build`로 명시한다.

## Docker 전체 스택

네 프로젝트가 `/workspace/modam-{chat,agi,rag,ontology}` 구조여야 한다. compose는 AGI 저장소 `deployment/compose.yaml`에 있다. RAG/ONTOLOGY는 아직 실행 서비스가 없으므로 생성/복제하지 않는다.

1. `deployment/compose.env.example`을 Git 제외 `.local/compose.env`로 복사하고 충분한 URL-safe 랜덤 DB 비밀번호와 신뢰하는 CA bundle을 지정한다. 키 값은 `.local/groq.env`에만 둔다.
2. AGI 저장소에서 다음을 실행한다.

```bash
docker compose --env-file .local/compose.env -f deployment/compose.yaml up --build -d
docker compose --env-file .local/compose.env -f deployment/compose.yaml exec agi modam-create-user your-id --admin
```

3. `http://127.0.0.1:3300`에서 로그인한다. Postgres/AGI/워커는 Docker 내부 네트워크이고 BFF만 loopback 포트를 공개한다.

compose가 DB health 후 immutable Alembic migration을 수행하고 API/워커를 시작한다. data volume을 보존한다. `down -v`는 데이터 삭제이므로 일반 정리/배포 명령으로 쓰지 않는다. CA는 빌드 secret 및 runtime read-only mount이며 TLS 검증을 끄지 않는다. Groq 키는 worker에만 env_file로 주입하며 image에 복사하지 않는다.

## 외부 운영 배포 상태

현재 관리형 환경에는 운영 서버 자격증명·도메인·포트 공개 기능이 연결되어 있지 않다. 따라서 위 loopback 주소는 사용자 PC에서 직접 접속하는 공개 주소가 아니다.

기존 주소 `https://orbit-agi-chat.qkrwnsh1592.chatgpt.site`는 소유자 제한 정적 데모로 유지한다. Sites는 Cloudflare Worker HTTP handler를 지원하지만 Fastify/Python/PostgreSQL 프로세스를 그대로 호스팅하지 않는다. 외부에서 접근 가능한 별도 AGI/BFF origin 없이는 이 workspace loopback에 접속할 수 없다. 이번 수정본을 로그인만 뜨고 API가 동작하지 않는 정적 사이트로 재배포하지 않는다.

운영 서버가 제공되면 동일 compose를 배치하고 TLS reverse proxy에서 도메인의 `/`와 `/api`를 BFF로 연결한다. `MODAM_NODE_ENV=production`, `MODAM_PUBLIC_ORIGINS=https://실제도메인`을 명시한다. 게이트웨이 request/rate limit, DB backup·보존 정책, worker 모니터링과 재시작을 운영 환경에서 검증한다. 운영 서버/도메인 정보가 확인되면 실제 접근 URL을 별도 검증한다.
