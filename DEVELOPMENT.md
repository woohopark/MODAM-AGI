# 프로젝트별 개발 기준

상태: 승인된 설계. 기존 한 코드베이스·직접 DB 연결·Local 모델 전제는 새 설계에서 사용하지 않는다.

- AGI는 오케스트레이션·Groq·MCP Client·평가/관측을 담당한다. RAG/ONTOLOGY 내부 구현·DB를 직접 호출하지 않는다.
- RAG는 문서 원천·Chunk·임베딩·색인, ONTOLOGY는 정의·매핑·KG를 각각 소유한다. 분산 작업의 실패/중복/버전을 명시한다.
- 기대 행동 → 실패 테스트 → 최소 구현 → 통과 → 정리 순서로 개발한다. 경계 대역·실제 MCP·실제 Groq 결과를 구분한다.
- 첫 구현부터 고정 테스트 데이터셋·구조화 로그·단계 트레이스를 포함한다. CoT·비밀·기업 원문을 일반 로그에 남기지 않는다.
- 신원·권한은 검증된 서버 정책을 사용하고 호출/실행 직전에 현재 상태를 확인한다. 도구 결과를 모델의 실행 주장과 구분한다.
- 키/비밀번호는 환경 설정으로 관리한다. Cloud 전송 범위·TLS/CA·프록시 신뢰를 지킨다.
- 언어·웹서버·DB·프레임워크·파서·임베딩은 프로젝트별 구현 전 검증 후 고정한다. 이전 의존성을 새 아키텍처의 확정 기술로 보지 않는다.

[AGI 개발 계획](IMPLEMENTATION_PLAN.md) · [RAG 개발 계획](https://github.com/woohopark/MODAM-RAG/blob/main/IMPLEMENTATION_PLAN.md) · [ONTOLOGY 개발 계획](https://github.com/woohopark/MODAM-ONTOLOGY/blob/main/IMPLEMENTATION_PLAN.md).
온톨로지 상세 방법론은 [별도 프로젝트 문서](https://github.com/woohopark/MODAM-ONTOLOGY/blob/main/ONTOLOGY_METHODOLOGY.md)를 따른다. 각 프로젝트의 초기 완료 조건은 해당 PRD/EVALUATION을 기준으로 한다.
