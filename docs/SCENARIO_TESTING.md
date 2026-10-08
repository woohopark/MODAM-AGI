# 샘플·전체 시나리오·독립 평가

## 세 가지 검증을 분리한다

| 종류 | 목적 | 모델·데이터 | 결과 해석 |
|---|---|---|---|
| TDD/회귀 | 권한·규칙·승인·중복·예외를 재현 | 모델 경계 대역, 실제 업무 로직·격리 DB | 기능 정확성 |
| offline 시나리오 | 예시의 모든 단계를 연결 | 유한한 고정 입력/응답 어댑터, 실제 검색·그래프·재고·승인·초안 | 모델 없이 연결 흐름 검증 |
| groq 시나리오 | 실제 한국어 해석·근거 답변과 지연 | Groq, 같은 합성 데이터·질문 | 모델 포함 정확도·응답 시간 |

offline은 자연어를 일반적으로 이해하는 모델이 아니다. samples/warehouse_poc.json의 정확한 질문을 의도로 변환하고 검색한 근거를 인용하는 유한한 대역이다. 권한·문서 접근·검색·관계 탐색·재고 차감·알림·승인·초안은 대역이 아닌 실제 서비스 로직이다. 현재 그래프는 SQL 속성 그래프, 검색은 문자 n-gram TF-IDF 코사인 유사도다. Neo4j 및 의미 임베딩 성능으로 보고하지 않는다.

## 샘플 내용

- 계정: sample_admin(관리), sample_accounting(회사 문서 조회), sample_field(창고 B 조회·출고·발주 제안), sample_inventory(창고 B 조회·제안·승인·실행).
- 창고 B, 물품 C, 최초 재고 108개, 미입고 수량 0개.
- 그래프: 창고 → 재고 → 물품 및 재고 → 발주 규칙 → 물품. 초안 생성 후 창고 → 초안 → 물품도 연결한다.
- 합성 규칙: 10개 미만이면 검토, 목표 재고 50개, 추천 수량 = max(0, 목표 - 현재 - 미입고).
- 합성 규정 두 개 및 접근 불가 finance 문서 한 개. 문서 출처·위치·버전과 검색/컨텍스트/인용 횟수를 보존한다.
- 100개 출고 → 재고 8개 → 42개 제안 → 담당자 승인 → 발주서 초안. 실제 ERP에는 등록하지 않는다.

## 직접 실행

저장소 루트에서 다음을 실행한다. Docker와 API 키 없이 offline 실행이 가능하다.

```bash
uv sync --frozen
uv run python -m modam.demo seed
uv run python -m modam.demo serve --mode offline --port 8001
```

별도 터미널에서:

```bash
uv run python -m modam.demo chat --user sample_accounting --message '창고 B의 물품 C 100개 발주해 줘'
uv run python -m modam.demo chat --user sample_accounting --message '회사 발주 승인 규정을 알려줘'
uv run python -m modam.demo issue --user sample_field --quantity 100 --event-id manual-outbound-1
uv run python -m modam.demo inventory --user sample_field
uv run python -m modam.demo graph --user sample_field
uv run python -m modam.demo notifications --user sample_inventory
uv run python -m modam.demo chat --user sample_field --message '창고 B 물품 C 재고와 후속 업무를 확인해줘'
uv run python -m modam.demo chat --user sample_field --message '창고 B 물품 C 42개 발주 제안해줘'
```

마지막 출력의 data.approval_id를 사용한다:

```bash
uv run python -m modam.demo approve --user sample_inventory --approval-id <승인ID>
uv run python -m modam.demo execute --user sample_inventory --approval-id <승인ID>
uv run python -m modam.demo execute --user sample_inventory --approval-id <동일승인ID>
```

같은 실행은 동일 초안을 반환하며 미입고 수량을 다시 더하지 않는다. 승인 이후 재고/원천 revision이 바뀌거나 요청자·승인자 권한이 회수되면 실행을 거절한다. 동일 event-id의 다른 내용은 충돌 오류다.

샘플은 .local/demo.db에 적재한다. 업무 DB를 초기화하지 않는다. 반복 seed는 기존 재고·비밀번호·초안을 보존하고 필요한 demo 관리 계정만 추가할 수 있다. 생성 비밀번호는 .local/demo-credentials.json(0600)에만 있으며 Git과 로그에 포함하지 않는다. CLI가 파일을 읽어 로그인하고 작업 후 자기 세션을 폐기하므로 토큰/비밀번호를 복사할 필요가 없다.

실제 Groq는 안전하게 GROQ_API_KEY를 주입하고 서버·chat 명령을 모두 --mode groq로 실행한다. offline 고정 질문 제한은 Groq 모드에 적용하지 않는다. 실제 제공 모델은 MODAM_GROQ_MODEL로 지정한다.

## 독립 평가·성능 측정

```bash
# 빠른 기능·컴포넌트 측정
uv run python -m modam.demo evaluate --mode offline --repeat 5 --warmup 1 --output .local/reports/offline-asgi.json
# 실제 서버·소켓을 포함하는 같은 시나리오
uv run python -m modam.demo evaluate --mode offline --transport http --repeat 5 --warmup 1 --output .local/reports/offline-http.json
# 실제 모델 포함 평가: 키 필요, 먼저 소량 실행
uv run python -m modam.demo evaluate --mode groq --transport http --repeat 1 --warmup 0 --output .local/reports/groq-http.json
```

각 반복은 새로운 임시 SQLite DB에서 시작한다. 수동 데모 DB와 PostgreSQL 업무 DB를 변경하지 않는다. 워밍업 결과는 따로 기록하고 측정 표본에서 제외한다. 적재·스키마 생성·로그인은 측정 시간에 포함하지 않는다. 리플레이는 별도 단계로 측정하여 캐시 응답을 모델 처리 속도로 섞지 않는다.

JSON 보고서에는 모드·제공자·모델·데이터 버전/해시·Git SHA/dirty 상태·Python·CPU 수, 개별 검증 결과, 성공/실패 반복 수, 실제 모델 호출 시도 수, 단계별 시간과 p50/p95/평균/최대값을 기록한다. p50/p95는 nearest-rank 방식이다. 성공한 반복만 지연 통계에 넣고 실패는 결과 목록에 유지한다. 필수 검사 실패 시 프로세스 종료 코드는 1이다. 키 없음은 차단 오류이며 Groq 통과로 집계하지 않는다.

전체 흐름 시간은 권한 거절·규정 7질문·출고·그래프·알림·분석·발주 제안·승인·초안·반복 검사를 포함한다. 단일 Chat 지연과 다르다. ASGI는 소켓 시간을 제외하고 HTTP는 로컬 소켓을 포함한다. 둘 다 운영 네트워크·동시 부하·대량 데이터 성능을 대신하지 않으며 고정 응답 결과는 LLM 성능이 아니다. 토큰 사용량/요금은 현재 보고서에서 측정하지 않는다.

## TDD와 실제 DB 검사

```bash
uv run pytest tests/test_business.py tests/test_evaluation.py -q
uv run pytest -q -m 'not postgres'
uv run python scripts/test_postgres.py
```

새 업무의 기대 결과를 테스트로 먼저 정의하고 실패를 확인한 뒤 구현한다. 독립 평가기는 모델 변경 시 같은 질문·데이터로 비교한다. PostgreSQL 검사는 실제 트랜잭션·동시 요청·영속성까지 다루며 새 격리 DB만 생성/제거한다.

## 현재 범위

세 가지 사용자 예시와 추가 질문·근거 충돌·권한 회수·중복 처리를 검증한다. PDF/Excel/HWP 파서·Wiki·의미 임베딩·Neo4j·실제 SAP 커넥터·전사 온톨로지 구축은 이 샘플 검증의 완료 주장에 포함하지 않는다. 규정은 현재 텍스트 적재 API를 사용한다. 오프라인 평가는 검색 근거와 규칙의 정확성을 검사하지만 실제 LLM의 일반화 능력은 별도로 평가한다.
