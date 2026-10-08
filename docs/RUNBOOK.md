# Foundation 실행 안내

기존 modam.main, modam.demo, DB 시작/마이그레이션 명령은 현재 코드에서 제거됐다.
현재는 Python 라이브러리와 평가 CLI다. 공개 HTTP 포트·AGI 배포 주소는 없다.

```bash
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/modam
uv run pytest -q
uv run modam-evaluate --repeat 3 --warmup 1 --output .local/reports/boundary.json
uv run modam-evaluate --mode groq --output .local/reports/groq.json
uv build
```

Groq 키는 환경의 GROQ_API_KEY로 주입한다. MODEM이 아닌 MODAM_GROQ_MODEL/MODAM_GROQ_TIMEOUT_SECONDS를 사용한다. .env 자동 로딩은 없다. 프록시/CA/TLS 검증을 유지한다. 모델 후보 제공 여부는 실제 키·계정으로 확인한다.
평가 종료 코드: passed 0, failed 1, blocked 2. Groq CLI는 MCP 미연결 상태의 계획 검사이며 전체 PoC 검증이 아니다.
보고서는 .local/reports에 생성한다. JSON logs는 Observer(stream=...)으로 안전한 저장 스트림을 주입할 수 있다. 트레이스 조회는 Observer.spans()다. 현재 저장 수명은 프로세스와 Observer 수명이다.

기존 코드 조회: git show baseline-monolith-cadea94:src/modam/api.py.
기존 DB/볼륨은 보존하며 첫 묶음은 접속/초기화하지 않는다. 신규 영속화 구현 시 별도 DB로 검증한다.

## 현재 작업 환경의 Groq 설정

사용자 제공 키는 Git 제외 .local/groq.env(권한 0600)에 저장하고 .local/with-groq(권한 0700)로 실행 시 환경변수에 주입한다. 전역 셸 환경이나 다른 클라우드 환경에 자동 등록한 것은 아니다. 이 두 파일은 현재 환경의 로컬 설정이며 복제/패키지에 포함되지 않는다.

```bash
.local/with-groq uv run modam-evaluate --mode groq --output .local/reports/groq-live.json
```

검증된 현재 모델은 openai/gpt-oss-120b이며 호출 제공자는 Groq다. 환경변수 MODAM_GROQ_MODEL로 교체 가능하다. 기존 llama-3.3-70b-versatile은 현재 제공 목록에 없으며 model_not_found로 구분한다. 프로세스 종료 시 실행 환경변수는 사라지고 로컬 설정 파일은 유지된다.
