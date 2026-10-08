# API 계약 계획

기준: [PRD](../PRD.md). 초기 접두사는 `/v1`. 인증은 `Authorization: Bearer <token>`. 아래는 목표 계약이며 미구현 항목을 배포 가능한 API로 해석하지 않는다. 실제 구현 계약은 생성된 OpenAPI와 구현 상태 기록을 확인한다.

## 첫 개발 묶음

| API | 권한·입력 | 결과 |
|---|---|---|
| GET /health/live, /health/ready | 공개, 비밀/내부 주소 제외 | 프로세스 상태, DB 사용 가능 여부 |
| POST /v1/auth/login | ID/PW | token, 만료 시각 |
| POST /v1/auth/logout | 로그인 | 현재 세션 폐기 |
| GET /v1/auth/me | 로그인 | 사용자·현재 Role |
| POST/GET /v1/admin/roles | Admin | 업무별 권한·범위 정의 |
| POST/GET /v1/admin/users | Admin | ID/PW/Role 생성·목록, PW는 반환 안 함 |
| PATCH /v1/admin/users/{id} | Admin | Role·활성 상태 변경 |
| POST /v1/permissions/check | 로그인 | 업무·범위의 현재 허용/거절 |
| POST /v1/approvals | 해당 제안 권한 | 업무·범위·매개변수·중복방지 키, 승인 대기 |
| POST /v1/approvals/{id}/decision | 해당 승인 권한 | 승인 또는 반려, 실행 완료와 구분 |
| GET /v1/approvals | 로그인, 소유/승인 범위 | 접근 가능한 승인 상태 |
| GET /v1/admin/audit | Admin | 최소 실행 근거·시간·상태 |
| GET /v1/admin/model | Admin | 키 제외 제공자·모델·키 존재 상태 |
| POST /v1/chat | 로그인, Cloud 전송 허용 | message, request_id, conversation_id; 구조화 의도·권한 판단·준비 상태 |

초기 업무 목록: inventory.read, procurement.propose, procurement.approve, procurement.execute, documents.read. 데이터 범위는 문자열 식별자 또는 Admin이 지정한 `*`다. 최초 Admin 생성은 CLI다. Cloud 호출 전에 `cloud_allowed=true`를 명시한다. 첫 묶음에서 Chat은 의도·권한 판단까지만 수행하고 미연결 도구는 `not_available`로 응답한다.

## 후속 API 묶음

- 온톨로지 정의/버전/검토, 원천 매핑, 데이터 적재, 정의·실체 그래프 조회.
- 문서 첨부·처리 상태·검색·Wiki 생성·삭제/갱신 및 Hit 집계.
- 모델 설정 수정·검증 및 현재/대기 적용 버전. 키 값의 API 입력/반환 금지.
- 재고 이벤트·문제 분석·발주 초안·내부 알림 및 확인 상태.
- 대화 이력·업무 상태·스트리밍 이벤트. 다른 사용자 대화 접근 금지.

## 오류·중복 계약

401: 인증 실패/만료. 403: 권한 또는 Cloud 전송 불가. 404: 미존재/접근 불가 대상. 409: 재사용 키의 내용 충돌·상태 충돌. 422: 입력 오류. 503: 모델·DB 준비 불가. 응답은 안전한 오류 코드와 메시지를 포함하며 비밀·제한 데이터·원시 모델 오류를 포함하지 않는다.

승인 중복방지 키는 사용자별 유일하며 내용이 같으면 기존 결과, 다르면 409다. Chat request_id는 사용자별 유일하며 동시 중복은 재호출하지 않는다. 모델 실패 후 재시도 정책은 명시하고 기존 실패를 완료로 반환하지 않는다.
