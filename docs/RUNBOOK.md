# 실행 안내

Python 3.12와 uv, Docker Compose가 필요하다. 화면은 이 저장소에 없다. 각 명령은 저장소 루트에서 실행한다.

## 개발 환경

```bash
uv sync --frozen
uv run python scripts/start_postgres.py
uv run alembic upgrade head
uv run python -m modam.cli bootstrap-admin --username admin
uv run uvicorn modam.main:app --host 127.0.0.1 --port 8000
```

DB 시작 스크립트는 `.local/runtime.env`에 개발용 무작위 DB 비밀번호와 접속 설정을 권한 0600으로 생성한다. 기존 파일과 DB 볼륨을 재사용하며 데이터를 초기화하지 않는다. `.local`은 Git에서 제외한다. PostgreSQL은 loopback에만 바인딩한다. Admin 생성은 빈 사용자 DB에서만 가능하고 비밀번호는 터미널에서 숨김 입력한다. Admin 관리 권한이 일반 업무 실행 권한을 자동 부여하지 않는다.

설정 우선순위는 프로세스 환경변수 > `.env` > `.local/runtime.env` > 기본값이다. `.env.example`은 형식 참고용이며 그대로 복사하면 자동 생성 DB 설정을 덮어쓸 수 있으므로 실제 접속 설정을 확인한다. Docker 없는 단순 개발/테스트는 SQLite를 사용할 수 있지만 PostgreSQL 검증을 대신하지 않는다.

`/health/live`는 프로세스, `/health/ready`는 DB 스키마 사용 가능 여부를 검사한다. 모델 키 준비 여부는 인증된 Admin의 `/v1/admin/model`로 별도 확인한다. DB가 준비됐다고 모델과 업무 도구가 준비된 것은 아니다.

## Groq

- 키는 환경 설정의 `GROQ_API_KEY`에 안전하게 등록한다. 소스·명령 인자·문서에 값을 넣지 않는다.
- 기본 모델 후보는 `llama-3.3-70b-versatile`이며 `MODAM_GROQ_MODEL`로 교체한다. 실제 계정의 제공 모델과 출력 품질을 확인해야 한다.
- `MODAM_GROQ_TIMEOUT_SECONDS`의 기본값은 30초다. 환경 설정을 변경하면 API 프로세스를 재시작한다.
- 플랫폼 프록시와 CA 설정을 유지하고 TLS 검증을 비활성화하지 않는다. 목적지는 `api.groq.com`이다.
- `/v1/chat`에는 사용자별 고유 `request_id`, `message`, 외부 전송 허용 시 `cloud_allowed=true`를 전달한다. 승인 없는 전송은 모델 호출 전에 차단한다. 기업 자료는 승인된 전송 범위에서만 사용한다.
- 현재 Chat은 의도·권한 판단까지만 제공한다. 도구가 없는 업무는 `not_available`, 키가 없으면 `failed/model_key_missing`이며 실제 실행을 주장하지 않는다.
- 현재 대화 원문은 업무 DB에 저장한다. 운영 사용 전 보존 기간·마스킹·삭제 정책을 정한다. 감사 API는 원문·비밀을 반환하지 않는다.

## 검증

```bash
uv run ruff check src tests scripts migrations
uv run ruff format --check src tests scripts migrations
uv run mypy src/modam
uv run pytest -q -m 'not postgres'
uv run python scripts/test_postgres.py
uv run python scripts/smoke_http.py
uv run alembic check
```

PostgreSQL 테스트와 HTTP smoke는 `modam_test_<uuid>`라는 새 격리 DB를 만들어 검사 후 해당 DB만 제거한다. 테스트 실행 계정에는 새 DB 생성 권한이 필요하다. 기존 업무 DB를 초기화하지 않는다. smoke는 임시 사용자와 실제 HTTP 프로세스를 사용하고 Groq 키를 비워 오류 처리를 검사한다. 실제 Cloud 추론 평가는 별도다.

## 중지·재시작

API는 해당 프로세스를 중지하고 같은 명령으로 다시 시작한다. PostgreSQL은 `docker compose --env-file .local/runtime.env stop postgres`로 중지하고 시작 스크립트로 복구한다. 개발 데이터 보존을 위해 `down -v`를 사용하지 않는다. 기존 사용자·세션·승인 상태는 DB에 보존된다. 프로세스 중단 중 Chat 요청은 자동 재실행하지 않으며 확인 후 새 request_id로 재요청한다.
