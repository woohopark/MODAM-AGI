# MODAM-AGI 최소 Observability

상태: 로컬 최소 구현 완료 · 영속 감사/관리 조회/운영 수집은 후속. 첫 오케스트레이션 구현부터 구조화 로그·단계 트레이스·기본 지표를 포함한다. 초기에는 로컬 안전한 저장/조회로 시작하고 외부 수집 플랫폼 선정은 후속 결정이다.

## 구조화 로그

필수 필드: timestamp(UTC), event_name, request_id, run_id, trace_id, span_id, parent_span_id, 가명 subject_ref, step, tool/server, status, error_code, duration_ms, model_id, config/prompt/contract_version.
권한 결정에는 action/scope/policy_version·허용/거절 이유 코드를, 승인에는 approval_ref·대상/매개변수 해시·source_version·결정/실행 상태를 기록한다.

API 키·비밀번호·bearer token·원시 Groq 응답·CoT 원문·기업 문서 원문은 일반 로그에 기록하지 않는다. 대화/업무 데이터 저장은 관측 로그와 별도로 접근·보존·삭제 정책을 정한다.

## 단계 트레이스

request → identity/authorization → model.interpret → plan → mcp.call → verify → model.answer → response.
승인 대기 이후 재개는 이전 run/approval과 연결하고 새 실행 단계를 기록한다. MCP 측에는 trace_id를 전파하며 원격 단계 시간을 클라이언트 측 왕복 시간과 구분한다. ReAct는 행동·관찰·판단 요약으로 기록한다. ToT는 초기 필수가 아니다.

## 최소 지표

성공·거절·실패·결과 불명 수, 전체/단계 p50·p95, Groq 실제 호출 시도·재시도·타임아웃, MCP 호출·오류, 승인 대기·결정·실행 상태, 근거 사용·인용 횟수.
Groq가 제공한 usage만 토큰 수로 기록하며 누락은 null이다. 요금 추정은 가격 버전이 있을 때만 별도 계산한다. 검색 Hit와 답변 인용을 동일 지표로 합치지 않는다.

## 완료 조건

한 요청의 Groq·MCP·판단·최종 상태를 trace_id로 조회한다. 비밀 문자열 검사에 누출 0건, 권한 거절은 제한 근거/원문 없이 조회 가능하다. 관측 실패가 업무 완료를 위조하지 않으며 변경 감사 기록의 저장 실패 처리 정책을 정의한다. 관리자 관측 API도 접근 제어한다.

## 현재 구현

Observer.events/선택 JSON stream과 Observer.spans()를 제공한다. 요청·계획·권한·도구·검증·답변 span을 같은 trace로 연결한다. 이벤트에는 UTC/event/request/run/trace/span/parent/step/status/호출 횟수/시간을 기록한다. Root span은 모델·프롬프트·설정 버전을 가진다. 키·메시지·근거 본문·예외 원문은 수집하지 않는다. exporter는 로컬 메모리이며 외부로 자동 전송하지 않는다. Observer.close()로 종료하고 사용 후 객체를 해제한다.

Root span의 subject_ref는 SHA-256 가명으로 기록한다. 정책 버전·승인 감사·관리 API·영속 보존은 인증/상태 단계에서 연결한다. 아직 영속 운영 관측 완료가 아니다. 모델/도구 p50/p95는 평가 span 통계로 제공한다. 실제 Groq usage는 제공된 숫자만 기록하고 누락은 null이다.
