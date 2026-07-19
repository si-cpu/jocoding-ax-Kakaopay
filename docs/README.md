# 문서 구조

이 폴더는 프로젝트 문서를 버전별로 정리한 곳입니다.

## 빠른 진입점

| 목적 | 문서 |
|---|---|
| 프로젝트 전체 발전 흐름 보기 | [`versions/v1_market_contradiction_assistant/PROJECT_EVOLUTION_SUMMARY.md`](versions/v1_market_contradiction_assistant/PROJECT_EVOLUTION_SUMMARY.md) |
| 최종 서비스 차터 보기 | [`versions/v1_market_contradiction_assistant/SERVICE_PROJECT_CHARTER.md`](versions/v1_market_contradiction_assistant/SERVICE_PROJECT_CHARTER.md) |
| 개발/실험 로그 보기 | [`versions/v1_market_contradiction_assistant/PIPELINE_EXPERIMENT.md`](versions/v1_market_contradiction_assistant/PIPELINE_EXPERIMENT.md) |
| 초기 출발점 보기 | [`versions/v0_anchor_event_mapper/PROJECT_CHARTER.md`](versions/v0_anchor_event_mapper/PROJECT_CHARTER.md) |

## 버전별 정리

### v0_anchor_event_mapper

초기 `Anchor Event Mapper` 시절 문서입니다. 핵심은 비정형 뉴스·공시·루머 입력을 공식 앵커 이벤트로 볼 수 있는지 먼저 구분하는 것이었습니다.

포함 문서:

- `PROJECT_CHARTER.md`
- `ANCHOR_EVENTS.md`
- `CONTEXT_ANCHORS.md`
- `OPENDART_HYUNDAI_STRIKE_REALDATA_RESULT.md`
- `PLUGIN_TEST_RESULTS.md`
- `USER_FACING_TEST_RESPONSE.md`
- `USER_FACING_TEST_RESPONSE_HYUNDAI_STRIKE.md`
- `USER_FACING_REALDATA_HYUNDAI_STRIKE.md`

### v1_market_contradiction_assistant

최종 `시장 불일치 해석 어시스트` 문서입니다. 핵심은 뉴스·공시·가격·수급이 서로 어긋날 때 가능한 설명 후보와 확인 질문을 구조화하는 것입니다.

포함 문서:

- `PROJECT_EVOLUTION_SUMMARY.md`
- `SERVICE_PROJECT_CHARTER.md`
- `PIPELINE_EXPERIMENT.md`

## 루트에 남겨둔 것

루트에는 실행과 진입에 필요한 파일만 남겼습니다.

- `README.md`
- `requirements-pipeline.txt`
- `scripts/`
- `plugins/`
- `submission_package/`

`output/`과 `tmp/`는 실행 결과물이므로 git에는 포함하지 않습니다.
