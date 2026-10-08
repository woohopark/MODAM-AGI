# MODAM-AGI 개발 에이전트 지침

현재 범위와 실제 검증은 STATUS.md와 docs/FOUNDATION_REVIEW.md를 먼저 읽는다.
요구사항은 PRD.md, 행동 원칙은 AGENT.md, 절차는 SKILL.md, 개발 기준은 DEVELOPMENT.md다.
루트의 현재 문서가 기준이며 docs/legacy는 변경하지 않는다.

- Groq만 사용한다. RAG/ONTOLOGY 구현·DB·색인·원천을 AGI에 추가하지 않는다.
- 인증된 서버 맥락과 현재 권한을 주입한다. 사용자/모델의 신원·권한 주장을 실행 권한으로 사용하지 않는다.
- Protocol로 모델·권한·도구 경계를 분리한다. 작은 계약을 사용하며 업무별 분기를 실행 엔진에 추가하지 않는다.
- 모델·도구의 입력/출력을 검증하고 호출·시간·근거 크기 한도를 지킨다.
- 기대 행동의 실패 테스트 → 최소 구현 → 통과 → 정리 순서로 진행한다.
- 평가 대역은 evaluation.py와 테스트에서만 사용한다. 대역 통과를 실제 모델/MCP/ERP 통과로 보고하지 않는다.
- CoT·키·인증 헤더·기업 원문·원시 오류를 로그/트레이스에 저장하지 않는다.
- uv만 사용하고 pyproject.toml과 uv.lock을 함께 갱신한다. 기능 단계에 필요한 의존성만 추가한다.
- 코드 변경 후 uv sync --frozen, Ruff lint/format, mypy strict, pytest를 실행한다.
- 평가 동작 변경 시 고정 데이터셋으로 평가한다. 패키지/데이터 경로 변경 시 wheel을 빌드·검사한다.
- DB·볼륨·사용자 데이터 삭제는 소스 정리와 별개다. 기존 기준점 baseline-monolith-cadea94를 보존한다.
- STATUS.md에 구현·대역·실제 연결·blocked와 다음 단계를 구분해서 기록한다.
