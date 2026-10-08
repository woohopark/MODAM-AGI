# 프로젝트별 시나리오 테스트 안내

새 구조의 평가 계획: [AGI](../EVALUATION.md), [RAG](https://github.com/woohopark/MODAM-RAG/blob/main/EVALUATION.md), [ONTOLOGY](https://github.com/woohopark/MODAM-ONTOLOGY/blob/main/EVALUATION.md).
AGI 단위/계약 → 각 MCP 서비스 통합 → 실제 Groq → 변경 도구를 포함한 전체 흐름을 구분한다. 신규 평가 CLI/데이터셋은 아직 구현하지 않았다.

이전 단일 서비스의 실행 명령·합성 샘플은 [이전 시나리오 문서](legacy/docs/SCENARIO_TESTING.md)에 보존한다. 현재 코드는 유지되어 있으나 향후 Groq 외 코드 삭제 시 해당 명령은 더 이상 사용하지 않는다. 이전 offline 성능은 새 MCP/Groq 성능이 아니다.
