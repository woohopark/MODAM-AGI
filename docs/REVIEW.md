# 코드·테스트 리뷰 · 2026-10-08

사용자 요청: 코드와 테스트를 리뷰하고 검증 통과 후 각 GitHub 저장소에 커밋/push.
이는 이번 변경의 명시적 Git 반영 승인이다. 자동 테스트가 운영 전반의 신뢰를 보장한다고 주장하지 않는다.

## 이번 리뷰와 보완

20개 초과 근거를 20개씩 나누어 현재 ACL을 검사하고 마지막 묶음이 거절되면 전체를 거절한다.
통합 fixture의 as_of를 테스트 실행 시점으로 주입한다. 원천 사실/버전과 stale 실패 규칙은 유지한다.

## 검사

CHAT npm run check 74개, AGI 단위/계약 44개 + 실제 HTTP/MCP 통합 2개,
RAG 17개, ONTOLOGY 19개: 전체 156개.
Python frozen uv/lock, Ruff/format, mypy strict, wheel 빌드와 문서/소스 diff를 확인한다.
실제 MCP/SQLite 프로세스 테스트는 모델 대역이다. 이전 실제 Compose/Groq 3턴·브라우저 결과와 구분한다.
Git 제외 비밀/런타임 DB/보고서/생성물을 커밋하지 않는다. 원격 main 변경 여부를 fetch로 확인한다.
GitHub CI는 push 후 별도로 결과를 확인한다.

## 허용 범위와 남은 제한

독립 서비스 초기 구현과 검증된 읽기 시나리오의 Git 반영이다.
의미 임베딩·binary HWP/OCR·실제 SAP/ERP·원격 관리·운영 HA/부하/백업·외부 HTTPS는 후속이다.
현재 실제 서비스 주소는 workspace 내부 http://127.0.0.1:3300이며 외부 공개 URL은 아직 없다.
