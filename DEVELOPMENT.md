# MODAM-AGI 개발 기준

2026-10-08 구현 검토 승인에 따라 다음 선택을 확정했다. 실제 적용 범위는 STATUS.md를 따른다.

| 구성 | 선택 | 적용 단계 |
|---|---|---|
| 언어/패키지 | Python 3.12, uv, uv.lock | 기반 구현 |
| 검증/모델 | Pydantic 2, pydantic-settings, 비동기 HTTPX, Groq만 사용 | 기반 구현 |
| 실행 엔진 | 명시적 비동기 상태 머신, 작은 Protocol 경계 | 기반 구현 |
| 관측 | JSON 구조화 로그, 로컬 OpenTelemetry SDK | 기반 구현 |
| 품질 | pytest/pytest-asyncio, Ruff 100자, mypy strict | 기반 구현 |
| HTTP 진입점 | FastAPI/Uvicorn | 인증 구현과 함께 다음 묶음 |
| 신원 | AGI 내부 ID/PW·복수 Role·현재 정책, 외부 인증 연결 가능 경계 | 다음 묶음 |
| 상태 DB | PostgreSQL, SQLAlchemy, Alembic | 다음 묶음 |
| MCP | 공식 Python SDK, Streamable HTTP | 실제 서비스 연결 묶음 |

첫 묶음에 불필요한 FastAPI/DB/Argon2/Alembic/LangGraph 의존성은 제거했다. 이후 선택된 기능을 구현할 때 다시 검증·설치한다. LangChain/LangGraph/Ollama, AGI 내부 pgvector/Neo4j는 기본 의존성이 아니다.

## 코드 기준

- SRP: 계획, 권한, 도구 스키마, 실행 상태, 관측, 평가를 분리한다.
- OCP/DIP: Model/Authority/Gateway Protocol을 주입하고 ToolSpec으로 읽기 도구를 확장한다.
- ISP/LSP: 작은 계약과 동일한 반환/오류 의미를 사용한다. 대역의 존재와 운영 연결을 구분한다.
- KISS/DRY: 필요한 경계에만 추상을 사용하고 동일 권한/상태 기준을 중복 구현하지 않는다.
- snake_case, PascalCase, 명시적 인자/반환 타입, UTC 포함 시간, extra=forbid 입력 검증.
- 사용자 메시지와 도구 자료는 데이터이며 시스템 지시가 아니다. SQL/Cypher/URL을 모델로부터 실행하지 않는다.
- 설정은 환경변수에서 주입한다. .env 자동 로딩과 이전 DB 설정 자동 재사용은 하지 않는다.
- Cloud 전송은 요청 동의와 서버 Authority.can_send 정책을 함께 검사한다.

## 검증

```bash
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/modam
uv run pytest -q
uv run modam-evaluate --repeat 3 --warmup 1
uv build
```

테스트는 순수 권한 규칙/상태 로직을 검사하고 모델/네트워크 경계를 대역으로 재현한다. 실제 MCP·PostgreSQL·Groq 검증은 별도 결과로 기록한다. 데이터셋 버전 변경과 검증 기준 변경은 검토 가능한 diff로 남긴다.
