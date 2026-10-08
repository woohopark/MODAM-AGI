# MODAM-AGI

처음 보는 업무 목표를 이해하고, 허용된 도구로 계획·수행·검증·재계획하는 범용 에이전트 프로젝트입니다.

초기 PoC는 SAP ERP 등 기업 시스템의 데이터를 객체·속성·관계로 정의하고, 온톨로지 → Knowledge Graph → LLM/RAG로 연결하는 흐름을 검증합니다. 사람이 검토하는 초기 설계 체계를 마련하고, 향후 반자동·자동 구축 가능성을 평가합니다.

현재 인증·권한 기반과 합성 샘플의 관계 조회·규정 검색·재고 알림·승인·발주서 초안을 연결했습니다. 모델 없이 전체 흐름을 재현하고 실제 Groq 평가와 분리해 성능을 측정할 수 있습니다. 실제 Groq 호출과 전체 PRD 성공은 아직 검증하지 않았습니다.

| 문서 | 내용 |
|---|---|
| [PRD.md](PRD.md) | 목표·요구사항·검증 기준 |
| [AGENT.md](AGENT.md) | 에이전트 행동 원칙 |
| [SKILL.md](SKILL.md) | 목표 해결 절차 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | DB·아키텍처·코딩·테스트·배포 참고 |

초기 모델 제공자는 Groq Cloud API입니다. 화면은 별도 저장소에서 개발합니다. [개발 계획](docs/IMPLEMENTATION_PLAN.md)과 [기술 설계](docs/ARCHITECTURE.md), [API 계약](docs/API_CONTRACT.md), [평가 계획](docs/EVALUATION.md)을 참조하세요.

개발 실행은 [실행 안내](docs/RUNBOOK.md), 구현 범위와 검증 결과는 [개발 상태](docs/STATUS.md)를 확인하세요.

샘플을 넣고 예시를 직접 실행하려면 [샘플·전체 시나리오·독립 평가](docs/SCENARIO_TESTING.md)를 확인하세요.
