# MODAM-AGI 진입 API 계약

상태: 후속 HTTP API 목표 계약이다. 첫 묶음은 라이브러리이며 HTTP API와 OpenAPI 서버는 아직 없다. 접두사 /v1, 인증된 사용자 맥락을 서버가 생성한다. ID/PW 로그인 및 Admin 사용자/Role 요구사항은 유지하되 초기 내부 인증을 승인했으며 다음 묶음에서 구현한다.

| 계약 | 목적·입력 | 결과 |
|---|---|---|
| 인증·사용자·Role 관리 | ID/PW/Role 생성, 로그인, Role 회수 | 검증된 신원·현재 권한, 비밀 값 제외 |
| POST /v1/chat | request_id, conversation_id, message, cloud_allowed | run_id, 상태, 답변, 근거 참조, 오류 코드 |
| GET /v1/runs/{run_id} | 소유/관리 권한 | 단계·도구·승인·결과 상태 |
| 승인 요청/결정 | 변경 대상·매개변수·원천 버전, 승인자 결정 | 대기/승인/반려; 실행 완료와 구분 |
| GET /v1/admin/model | 관리 권한 | Groq 모델·설정 버전·키 준비 여부 |
| 모델 설정/검증 | 모델 ID·타임아웃·옵션 | 적용/대기·재시작 필요 여부 |
| MCP 설정/상태 | 허용 서버·도구·계약 버전 | 연결·인증·규격 상태, 비밀 제외 |
| 관측·평가 조회 | 관리 권한, 실행/데이터셋 ID | 안전한 로그·트레이스·지표 |
| RAG/온톨로지 관리 연결 | 검증된 관리 요청 | 담당 MCP 작업/상태; AGI 자체 적재 아님 |

상태 제안: completed, clarification_required, awaiting_approval, denied, failed, unknown, not_available. 상태 이름은 구현 전 계약 테스트에서 고정한다.

## 공통 규칙

request_id는 사용자 범위에서 유일하다. 같은 ID/같은 내용은 접근 권한 재확인 후 기존 결과를 반환하고 다른 내용은 충돌이다. 처리 중/결과 불명은 자동 완료 처리하지 않는다. 인증 실패·권한 거절·미존재/접근 불가·충돌·입력 오류·서비스 미준비를 구분한다. 업무 결과 상태와 HTTP 오류를 구분해 기록한다.

근거는 RAG document_id/version/chunk_id/location 또는 ONTOLOGY object_id/path/source_ref/definition_version/as_of를 참조한다. 검색 결과 원문을 공개 관측 API에 반환하지 않는다. 상세 경로·JSON 필드 확정은 구현 계획의 계약 단계에서 수행한다.

## 현재 내부 라이브러리 계약

`Engine.run(Request)`는 RunResult를 반환한다. Request의 subject_ref는 서버/테스트의 검증된 내부 맥락이며 공개 HTTP 요청 필드가 아니다. request_id, run_id, trace_id, status, message, error_code, evidence, model_calls, tool_calls, elapsed_ms, contract_version을 반환한다. 정확한 스키마는 src/modam/schemas.py다. 현재 요청 중복 저장/대화/승인/관리 API는 미구현이다. model_calls는 모델 경계 호출 수이며 실제 Groq 시도 수와 다르다.
