# MODAM-AGI

처음 보는 업무 목표를 이해하고, 허용된 도구로 계획·수행·검증·재계획하는 범용 에이전트 프로젝트입니다.

초기 PoC는 SAP ERP 등 기업 시스템의 데이터를 객체·속성·관계로 정의하고, 온톨로지 → Knowledge Graph → LLM/RAG로 연결하는 흐름을 검증합니다. 사람이 검토하는 초기 설계 체계를 마련하고, 향후 반자동·자동 구축 가능성을 평가합니다.

현재 저장소에는 요구사항과 개발 참고 문서만 있습니다.

| 문서 | 내용 |
|---|---|
| [PRD.md](PRD.md) | 목표·요구사항·검증 기준 |
| [AGENT.md](AGENT.md) | 에이전트 행동 원칙 |
| [SKILL.md](SKILL.md) | 목표 해결 절차 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | DB·아키텍처·코딩·테스트·배포 참고 |

초기 모델 제공자는 Groq Cloud API입니다. 화면은 별도 저장소에서 개발합니다. [개발 계획](docs/IMPLEMENTATION_PLAN.md)과 [기술 설계](docs/ARCHITECTURE.md), [API 계약](docs/API_CONTRACT.md), [평가 계획](docs/EVALUATION.md)을 참조하세요.
