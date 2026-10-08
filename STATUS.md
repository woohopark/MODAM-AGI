# MODAM-AGI 구현 상태

2026-10-08. 사용자 구현 검토 승인 후 첫 개발 묶음(계약·Groq 정리·실행/관측/평가 기반)을 구현했다.

## 구현

- Groq-only 비동기 HTTPX 어댑터, Pydantic 계획/답변 검증, 오류 안전 코드, 실제 시도 수/제공 usage.
- 현재 신원/권한/전송 정책을 주입하는 읽기 상태 머신. 전체/도구 시간 제한, 모델/도구 호출 한도, 제한된 재계획.
- 허용 도구/인자, 반환 근거 범위·현재 정책·freshness·출처 버전·전송 허용·인용 ID 검증.
- 로컬 JSON 로그와 OpenTelemetry span. 요청부터 단계까지 trace/run 연결, 원문/키/예외 원문 제외.
- 버전 고정 합성 14개 평가, 워밍업/반복, 실패 구분, 전체/단계 p50/p95 보고.
- uv.lock, Ruff/mypy/pytest, wheel/sdist 패키징, GitHub Actions 검사 정의.
- 이전 단일 서비스 소스·관련 의존성·테스트·마이그레이션 정리. 이전 기준점/Git 이력/문서 보존. DB/볼륨에는 접근하지 않았다.

## 이번 검증

- Ruff lint/format, mypy strict 통과.
- 단위/계약 테스트 29개 통과.
- 합성 경계 평가 14개 × 측정 3회 = 42개 통과(별도 워밍업 1회).
- wheel/sdist 빌드 및 wheel의 신규 코드/데이터셋 포함 확인.
- 실제 Groq 평가: 환경 키 미주입으로 blocked, 네트워크 시도 0회.
- 실제 MCP/DB/HTTP/승인/ERP: 이번 묶음에서 미구현·미실행.

CI 파일은 작성했으며 원격 Actions 실행 성공을 주장하지 않는다. 상세 증거는 docs/FOUNDATION_REVIEW.md와 .local/reports(로컬, Git 제외)에 있다.

## 후속

내부 ID/PW 인증·복수 Role 관리, FastAPI, PostgreSQL 실행/대화/승인 저장, 사용자별 요청 멱등성·재시작 복구 → 실제 두 MCP·위임/현재 ACL·연결 계약 → 별도 알림/발주 초안 도구·전체 변경 흐름.
현재 Engine은 내부 라이브러리이며 HTTP 진입점/로그인/영속 감사/배포 서비스가 없다. 대화 ID를 보내면 not_available이며 이력을 처리했다고 주장하지 않는다. 첫 묶음 통과는 전체 PRD 또는 범용 AGI 완성을 의미하지 않는다.

이전 44+8 테스트/오프라인 평가 기록은 docs/legacy에 보존하며 신규 통과로 집계하지 않는다.
