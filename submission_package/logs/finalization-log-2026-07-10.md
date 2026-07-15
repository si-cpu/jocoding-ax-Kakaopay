# Finalization Log - 2026-07-10

이 파일은 제출 패키지 완성 직전의 추가 보정 내역을 남긴 보조 로그입니다.

원본 대화 로그는 `logs/codex-export-2026-07-08.jsonl`에 그대로 포함되어 있으며, 이 파일은 원본 로그를 편집하거나 대체하지 않습니다.

## 최종 보정 요약

### 1. 프로젝트 차터와 README 정합성 보정

- `PROJECT_CHARTER.md`, `README.md`, `submission_package/README.md`, `submission_package/src/docs/PROJECT_CHARTER.md`를 비교했다.
- 마지막에 확정한 원칙 중 README에 약하게 반영된 항목을 보강했다.
- 보강한 항목:
  - 비확정 선행 신호는 단순 분석 보류로 끝내지 않고 가능한 경우 전환/회피 시나리오로 안내한다.
  - 이벤트 기준일은 발표 당일을 원칙으로 하되, 장마감 후 또는 휴일이면 다음 영업일 기준으로 계산한다.
  - 보조 이벤트 확인 구간은 기준일 이전 1주일, 기준일~3영업일, 3~5영업일, 5~10영업일로 나눈다.
  - 업종 확장은 KRX 업종 분류, 카카오페이증권 내부 종목 분류, 확장 보류 순서로 처리한다.

### 2. 경쟁사/유사 기능 분석 추가

- README에 `경쟁사/유사 기능 분석` 섹션을 추가했다.
- 비교 대상:
  - 증권 앱 뉴스/공시 탭
  - 주가 급등락 사유 설명
  - 뉴스 요약/감성 분석 도구
  - 리서치 리포트/전문가 콘텐츠
- 본 플러그인의 차이를 “왜 올랐는지 단정하는 기능”이 아니라 “입력을 분석 가능한 사건으로 봐도 되는지 먼저 구분하는 기능”으로 정리했다.

### 3. 차별점 추가

- README에 `차별점` 섹션을 추가했다.
- 핵심 차별점:
  - 호재/악재 즉답이 아니라 공식 확인 가능성 우선
  - 뉴스·루머·전망과 확정 사건 분리
  - 파업 단계 분리
  - 전환/회피 시나리오 제공
  - 투자 추천이 아니라 기준일 이후 주가증감 참고값 제공
  - 구간별 보조 이벤트로 단일 원인 오해 방지

### 4. 부적절한 요청 처리 원칙 추가

- README에 `부적절한 요청 처리 원칙`을 추가했다.
- 매수/매도 추천, 목표가, 수익률 보장, 루머 기반 단정, 내부자 정보 요청 등을 제한 또는 거절 대상으로 정리했다.

### 5. 향후 운영·업데이트 방향 추가

- README에 `향후 운영·업데이트 방향`을 추가했다.
- RSS는 현재 MVP에서는 사용하지 않지만, 저작권, 원문 저장, 중복 기사, 오염 검색어 문제가 해결될 경우 비확정 선행 신호 포착용으로 제한적으로 재검토할 수 있다고 정리했다.

### 6. 민감정보 포함 입력 처리 원칙 추가

- 사용자가 증권 앱 화면, 수익률 화면, 계좌 화면을 캡처해 올릴 때 개인정보 또는 계좌정보가 노출될 수 있다는 리스크를 반영했다.
- `민감정보 포함으로 분석 불가` 상태를 추가했다.
- 이미지/사진/캡처에 민감정보가 포함된 경우:
  - 분석하지 않는다.
  - 삭제 또는 민감정보 제거 후 재업로드를 안내한다.
- 텍스트에 민감정보가 포함된 경우:
  - 해당 부분을 `*`로 마스킹한다.
  - 앵커 이벤트 분석을 진행하지 않는다.
- 적용 파일:
  - `README.md`
  - `PROJECT_CHARTER.md`
  - `submission_package/README.md`
  - `submission_package/src/docs/PROJECT_CHARTER.md`
  - `submission_package/src/skills/anchor-event-mapper/SKILL.md`
  - `submission_package/src/skills/anchor-event-mapper/references/anchor-events.md`

### 7. 제출 ZIP 재생성 및 검증

- `submission.zip`을 다시 생성했다.
- ZIP 내부에 다음 항목이 포함되는지 확인했다.
  - `README.md`
  - `logs/codex-export-2026-07-08.jsonl`
  - `logs/finalization-log-2026-07-10.md`
  - `src/.codex-plugin/plugin.json`
  - `src/skills/anchor-event-mapper/SKILL.md`
  - `src/docs/PROJECT_CHARTER.md`
- ZIP 내부에 `.env`, `.DS_Store`, 중첩된 `submission.zip`이 포함되지 않도록 확인했다.

### 8. 카카오페이증권 인터뷰 스크립트 기반 포지셔닝 보정

- 사용자가 카카오페이증권 AI 서비스 센터장 인터뷰 스크립트를 공유했다.
- 스크립트의 핵심 요구는 초보 투자자가 매수·매도할 때 “어떻게 판단해야 할지 모르겠다”는 문제를 AI가 도와주는 것으로 해석했다.
- 동시에 인터뷰에서는 특정 정답보다 사용자가 납득하고 안심할 수 있는 “설득의 과정”과 “해답을 만들어 나가는 과정”을 중요하게 본다고 판단했다.
- 따라서 기존 기능은 유지하되 문서의 관점을 `교육용 뉴스 해석`에서 `매수·매도 전 판단 과정 보조`로 조정했다.
- 보정한 핵심 표현:
  - 매수·매도 결론을 대신 내리는 플러그인이 아니다.
  - 뉴스·공시·루머성 문장을 실제 판단 근거로 사용할 수 있는지 검증한다.
  - 공식 확인된 유사 이벤트 이후의 주가증감을 보여줘 사용자가 납득 가능한 판단 과정을 구성하도록 돕는다.
  - 투자 권유, 목표가, 매수·매도 추천은 하지 않는다.
- 적용 파일:
  - `README.md`
  - `PROJECT_CHARTER.md`
  - `submission_package/README.md`
  - `submission_package/src/docs/PROJECT_CHARTER.md`
  - `submission_package/src/.codex-plugin/plugin.json`
  - `submission_package/src/skills/anchor-event-mapper/SKILL.md`
