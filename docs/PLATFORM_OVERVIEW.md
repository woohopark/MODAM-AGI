# MODAM 공통 업무 PoC — 프로젝트별 요구사항 안내

상태: 승인된 설계 · 2026-10-08. 목표는 Chat으로 정확하고 신속하게 업무를 처리하는 것이다. Groq 단독 모델·AGI 오케스트레이션·별도 RAG/ONTOLOGY MCP 구조를 따른다. 화면은 별도 프로젝트다.

| 문서 | 제품 책임 |
|---|---|
| [MODAM-AGI PRD](../PRD.md) | 의도·맥락·계획·권한/승인·도구 호출·결과 검증·Evaluation/Observability |
| [MODAM-RAG PRD](https://github.com/woohopark/MODAM-RAG/blob/main/PRD.md) | PDF/Excel/HWP·Chunk/임베딩·근거 검색·Wiki·문서 지표 |
| [MODAM-ONTOLOGY PRD](https://github.com/woohopark/MODAM-ONTOLOGY/blob/main/PRD.md) | 객체/속성/관계·원천 매핑·검토/버전·KG·관계 탐색·반자동 구축 |

## 원 요구사항의 소유권

| 기존 항목 | 새 문서의 담당 | 분담 |
|---|---|---|
| AUTH-01~06 | AGI-AUTH-01~03 | 사용자/복수 Role·현재 권한 계약; 각 MCP가 자기 데이터 ACL 검증 |
| AGENT-01~06 | AGI-CHAT/ORCH/EVAL | 계획·맥락·검증·시간·중복 |
| ONT-01~06 | ONTOLOGY ONT-01~06 | 정의·매핑·검토·KG·경로·후보 |
| FLOW-01~05 | AGI-FLOW-01~03 | AGI 승인/제안, ONTOLOGY 경로·원천, 실제 변경은 소속 미정 도구 |
| DOC-01~06 | RAG-DOC/WIKI/OBS | RAG 검색 Hit, AGI 컨텍스트 사용/인용 |
| LLM-01~03 | AGI-LLM-01~02 | Groq만 사용, Local/Ollama/다른 제공자 계획 제거 |
| OBS-01~04 | AGI-OBS + 각 MCP 관측 | 요청·트레이스 연결, 판단 요약·출처·시간·오류 |
| 관리자 화면 요구 | AGI-ADMIN + 각 MCP 관리 계약 | 화면 별도, 백엔드 관리·상태·지표 계약 제공 |

## 대표 시나리오와 평가 소유권

A 권한 없는 발주: AGI가 거절하고 변경 도구 호출 0회.
B 회사 규정: RAG가 접근 가능한 근거를 반환하고 AGI가 근거 검증·답변·인용.
C 재고 문제: ONTOLOGY 관계/규칙 근거 + 업무 도구 최신 상태 → AGI 알림/제안/승인 → 별도 변경 도구 초안. 도구 미연결은 전체 완료로 표시하지 않는다.

평가 질문/기대값/데이터·계약 버전을 고정한다. 초기에는 규정 7개 중 5개, 원천 레코드/관계 각 10개 중 8개를 PoC 기준으로 유지한다. 제한 데이터 노출·무권한/무승인 실행·중복 변경은 허용하지 않는다. 성능·반자동 채택률은 우선 측정한다. 실시간 SAP·ERP 등록·전사 자동 구축·운영 SLA는 후속이다.

## 아직 결정하지 않은 사항

인증 구현 소속, 알림/발주 초안/ERP 변경 도구 소속, MCP 인증·전송·규격, AGI 상태 저장/프레임워크, RAG 임베딩/저장소, ONTOLOGY 그래프 저장소·후보 LLM 소속. 검토본은 이 항목들을 구현된 능력으로 표시하지 않는다.

## AGI 기반 전환 현황

AGI 첫 개발 묶음을 구현했다. 현재/후속 경계는 [STATUS](../STATUS.md)를 따른다. 내부 인증·FastAPI·PostgreSQL·명시적 상태 머신을 승인했으며 초기 상태 머신·관측·평가는 구현했다. 인증/HTTP/DB·실제 MCP·업무 변경은 아직 미구현이다. 다른 프로젝트의 문서나 저장소는 변경하지 않았다.
