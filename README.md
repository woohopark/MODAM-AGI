# MODAM-AGI

Groq만 사용하는 업무 오케스트레이션 기반이다. RAG/온톨로지는 독립 MCP 서비스로 연결하며 AGI가 문서·벡터·그래프 저장소를 직접 조회하지 않는다. 화면은 MODAM-CHAT이다.

현재 첫 개발 묶음: 비동기 Groq 어댑터, 한도가 있는 읽기 상태 머신, 주입형 현재 권한/전송 정책, 로컬 구조화 로그·OpenTelemetry 트레이스, 고정 합성 평가 데이터셋.
내부 ID/PW 인증·FastAPI HTTP·PostgreSQL 대화/작업/SSE·일반 Groq 멀티턴과 MODAM-CHAT Fastify 중계를 추가했다. 승인 실행·실제 MCP 연결은 후속이다. 외부 운영 주소는 아직 없고 workspace 내부 서비스만 실행한다.

[CHAT 연동 계약](docs/CHAT_INTEGRATION.md) · [Docker/실행/주소](docs/CHAT_DEPLOYMENT.md).

## 실행 및 검증

Python 3.12와 uv가 필요하다.

```bash
uv sync --frozen
uv run pytest -q
uv run modam-evaluate --repeat 3 --warmup 1 --output .local/reports/boundary.json
uv run modam-evaluate --mode groq --output .local/reports/groq.json
```

boundary는 명시적인 모델/도구/신원 경계 대역 평가다. 실제 LLM 정확도 또는 MCP 통합 결과가 아니다.
groq는 환경변수 GROQ_API_KEY를 사용해 합성 질문의 계획만 실제 호출하며 MCP는 미연결이다. 키가 없으면 blocked 및 종료 코드 2다. 키를 명령 인자/문서/Git에 넣지 않는다.

| 문서 | 내용 |
|---|---|
| [PRD](PRD.md) | 요구사항·성공 기준 |
| [AGENT](AGENT.md) / [SKILL](SKILL.md) / [AGENTS](AGENTS.md) | 제품 행동·목표 해결·개발 지침 |
| [DEVELOPMENT](DEVELOPMENT.md) / [패키지](docs/PACKAGES.md) | 승인 기술·컨벤션·설치 |
| [ARCHITECTURE](ARCHITECTURE.md) / [API_CONTRACT](API_CONTRACT.md) | 현재 경계와 후속 API |
| [MCP_INTEGRATION](MCP_INTEGRATION.md) | 독립 MCP 계약·미결정 항목 |
| [OBSERVABILITY](OBSERVABILITY.md) / [EVALUATION](EVALUATION.md) | 로그·트레이스·평가 |
| [계획](IMPLEMENTATION_PLAN.md) / [상태](STATUS.md) / [검토 결과](docs/FOUNDATION_REVIEW.md) | 구현·검증·제약 |
| [실행 안내](docs/RUNBOOK.md) | 새 명령과 복구 기준 |

[MODAM-RAG](https://github.com/woohopark/MODAM-RAG) · [MODAM-ONTOLOGY](https://github.com/woohopark/MODAM-ONTOLOGY) · [MODAM-CHAT](https://github.com/woohopark/MODAM-CHAT).
이전 단일 서비스는 [문서 이력](docs/legacy/INDEX.md)과 Git 기준점에 보존했다. 이전 44+8 테스트를 신규 구조 통과로 집계하지 않는다.

현재 환경에서는 `.local/with-groq uv run modam-evaluate --mode groq`로 로컬 보안 설정을 실행 환경변수에 주입한다. 로컬 키 파일/주입기는 Git 제외다. 현재 검증 모델은 Groq 제공 `openai/gpt-oss-120b`이며 실제 계획 7/7·합성 근거 답변 계약 1/1을 확인했다. 상세 범위는 [검토 기록](docs/FOUNDATION_REVIEW.md)을 따른다.
