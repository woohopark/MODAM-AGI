# MODAM-AGI MCP 연동 계약

상태: 승인된 application contract v0.1 제안. MCP 프로토콜 버전과 업무 계약 버전은 별개다. 아래 도구명은 신규 설계이며 현재 구현되어 있지 않다.

## 허용 도구

| 서비스 | 제안 도구 | AGI에서 사용하는 목적 |
|---|---|---|
| RAG | rag.search | 접근 가능한 규정·기록 근거 검색 |
| RAG | rag.documents.ingest / rag.jobs.get / rag.documents.update / rag.documents.delete | 관리 요청 전달·처리 상태·갱신·삭제 |
| RAG | rag.wiki.generate / rag.metrics.get | 선택 Wiki·관리 지표 |
| ONTOLOGY | ontology.definitions.get / propose / decide | 정의 조회·관리 후보·검토 |
| ONTOLOGY | ontology.mapping.validate / ontology.ingest / ontology.jobs.get | 원천 매핑 검사·적재·상태 |
| ONTOLOGY | ontology.objects.get / ontology.paths.query | 객체와 관계 경로·원천 근거 조회 |

클라이언트가 인증된 서버에서 capabilities/tools/list를 확인하고 허용된 도구만 사용한다. 도구 변경은 스키마/버전 검증 뒤 적용한다. 임의 동적 서버 URL·자유 쿼리는 허용하지 않는다.

## 신뢰와 전달

연결 인증으로 서비스 신원을 확인한다. 사용자 권한은 서버가 서명한 위임 맥락 또는 서버 간 검증 가능한 토큰으로 전달하고, LLM 도구 인자로 권한을 설정하지 않는다. PoC의 구체적 인증 방식은 구현 전 결정한다.
위임 맥락에 request_id, trace_id, run_id, 인증된 subject, 허용 action/scope, policy_version, expires_at을 연결한다. 서명/토큰 검증 실패 및 만료는 거절한다. 실제 raw token을 모델 입력이나 로그에 넣지 않는다.

## 업무 입출력

- 입력: 도구별 검증된 arguments, contract_version, 조회 한도·시간, 변경 시 idempotency_key 및 expected_version.
- 결과: status, data, evidence_refs, source/definition/index version, as_of, warnings, 안전한 error_code, timings, service_request_id.
- MCP 성공 응답이어도 업무 status 실패/충돌이면 completed로 취급하지 않는다. MCP 오류·isError·transport 오류도 구분한다.
- RAG 근거에는 cloud_allowed를 포함한다. 조회 가능과 Cloud 전송 가능은 별도이며 AGI가 전송 전에 재검사한다.
- ONTOLOGY 경로는 관계 사실이다. 인과관계나 실행 허가로 해석하지 않는다.

## 관측과 일관성

trace_id를 두 서비스까지 전파한다. RAG 검색 Hit는 RAG가 소유하고 AGI 컨텍스트 사용/인용은 AGI가 evidence_ref별로 기록해 결합한다. 원천 버전이 다른 결과는 충돌 또는 최신성 경고로 처리한다. 갱신과 조회의 분산 트랜잭션을 가정하지 않는다.

## 변경 도구

RAG/온톨로지 관리 변경은 해당 MCP의 관리 권한·검토·중복 계약을 따른다. 재고 출고·알림 전달·발주 초안·ERP 등록은 위 두 조회 도구에 포함하지 않는다. 소속과 승인/결과조회 계약이 정해질 때 별도 도구로 등록한다.
