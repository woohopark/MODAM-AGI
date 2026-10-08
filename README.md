# MODAM-AGI

Chat 업무 에이전트의 오케스트레이션 프로젝트다. 모델은 Groq만 사용하며 RAG와 온톨로지는 독립 MCP 서비스로 호출한다. Evaluation·Observability는 첫 구현부터 최소 로그·트레이싱·테스트 데이터셋을 포함한다. 화면은 별도 저장소다.

프로젝트별 설계 문서와 저장소 반영을 승인받았다. 현재 코드에는 이전 단일 서비스 구현이 남아 있으며 이번 변경은 문서에 한정한다. 코드 삭제·새 MCP 구조 구현 완료를 의미하지 않는다.

| 문서 | 내용 |
|---|---|
| [PRD](PRD.md) | AGI 목표·책임·요구사항·성공 기준 |
| [아키텍처](ARCHITECTURE.md) | 오케스트레이션·Groq·MCP·상태 경계 |
| [API 계약](API_CONTRACT.md) | Chat·사용자·승인·관리 계약 |
| [MCP 연동](MCP_INTEGRATION.md) | 인증·허용 도구·버전·근거·오류 |
| [Observability](OBSERVABILITY.md) | 최소 로그·단계 트레이스·지표 |
| [평가](EVALUATION.md) | 고정 데이터셋·TDD·실제 모델·성능 |
| [개발 계획](IMPLEMENTATION_PLAN.md) | 코드 정리와 신규 구현 단계 |
| [상태](STATUS.md) | 이전 구현과 신규 설계·검증의 구분 |

독립 프로젝트: [MODAM-RAG](https://github.com/woohopark/MODAM-RAG) · [MODAM-ONTOLOGY](https://github.com/woohopark/MODAM-ONTOLOGY).

[플랫폼 전체 책임](docs/PLATFORM_OVERVIEW.md) · [문서 분리·게시 기록](docs/REVIEW.md) · [개발 기준](DEVELOPMENT.md) · [에이전트 원칙](AGENT.md) · [절차](SKILL.md).
이전 설계/검증 결과는 [이력](docs/legacy/INDEX.md)에 보존한다. 다른 프로젝트 전체 문서는 각각의 저장소에서 관리한다.
