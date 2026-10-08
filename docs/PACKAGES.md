# 패키지 구성

Python >=3.12,<3.13, uv로 관리하며 정확한 직접/전이 버전·해시는 uv.lock에 고정한다.

| 현재 직접 의존성 | 잠긴 버전 | 목적 |
|---|---|---|
| pydantic | 2.13.5 | 모델/도구/근거/상태 계약 |
| pydantic-settings | 2.15.0 | 환경변수·SecretStr·설정 검증 |
| httpx | 0.28.1 | Groq 비동기 연결·타임아웃·테스트 transport |
| opentelemetry-sdk | 1.45.1 | 로컬 span/trace 수집 |
| pytest | 9.1.1 | 회귀/계약 테스트 |
| pytest-asyncio | 1.4.0 | 비동기 테스트 |
| Ruff | 0.16.10 | lint/format |
| mypy | 1.20.2 | strict 타입 검사 |

Hatchling은 빌드 도구다. uv sync --frozen은 설치 시 잠금을 변경하지 않는다.
LangGraph/LangSmith/단일 서비스 DB·서버 의존성은 제거했다. FastAPI/Uvicorn·SQLAlchemy/psycopg/Alembic·Argon2·공식 MCP SDK는 해당 구현 단계에 설치·고정한다. 선택 기술과 현재 설치 패키지를 구분한다.

wheel에는 modam 코드와 data/agi-scenarios-v1.json을 포함한다. 기업 데이터/평가 결과/.env는 패키지나 Git에 넣지 않는다.
