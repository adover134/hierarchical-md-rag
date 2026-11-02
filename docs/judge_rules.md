# 채점기 규칙 (현재: 루브릭 v2)

이 문서는 **지금 쓰는 채점 규칙**의 기준 문서다. 규칙이 바뀐 이유와 검증은 [`judge_improvement.md`](judge_improvement.md)에 있다. 아래 "루브릭 전문"은 코드(`scripts/claude_judge.py`의 `INSTRUCTIONS_V2`와 `src/evaluation/llm_judge.py`의 `JUDGE_SYSTEM_PROMPT`)에서 그대로 가져온 것이고, 서브에이전트가 읽는 `rubric.md`(`--rubric v2`)와 같다. 규칙을 고칠 때는 코드와 이 문서를 같이 고친다.

## 원칙

- 생성은 로컬 `gpt-oss:20b`, 채점은 항상 Claude 서브에이전트(Opus)다. 별도 API 키는 쓰지 않는다. gpt-oss로는 채점하지 않는다.
- 채점자는 항목이 어느 시스템·실행에서 나왔는지 모른다(`claude_judge.py export`가 시스템·실행 식별 없이 섞어 10건씩 배치로 낸다).
- 점수는 4개 축 모두 0~5 정수이고 축마다 한 문장 근거를 쓴다. 보고하는 모든 점수 문서에 "심사: Claude(서브에이전트)"와 루브릭 버전을 적는다.

## 요약: 축과 규칙

| 축 | 무엇을 보나 | 볼 때 쓰는 정보 |
|---|---|---|
| Correctness | 주된 값이 맞는가 | 질문, 기대 답변, 생성 답변 |
| Answer coverage | 주된 값이 빠짐없이 들어 있는가 | 질문, 기대 답변, 생성 답변 |
| Faithfulness | 답변이 context에 근거하는가(환각 없음) | `context`만 |
| Context relevance | context가 질문에 관련 있는가 | `context`만 |

| 규칙 | 한 줄 요약 |
|---|---|
| 1 주된 값 | 기대 답변의 괄호 밖 값이 주된 값, 괄호 안 내역은 부차 정보 |
| 2 Correctness | 주된 값만으로 판단. 모두 맞으면 5점, 하나 틀리거나 빠지면 최대 3점 |
| 3 Answer coverage | 주된 값이 모두 있는가만 본다. 괄호 안 내역 누락은 감점 없음 |
| 4 표기와 라벨 | 숫자 표기 차이는 같은 값. 금액 이름(기초금액, 사업비 등)이 달라도 값이 같으면 감점 없음 |
| 5 비교 질문 | 주된 사실은 선택한 대상(과 있으면 그 값) |
| 6 답변 거부 | Correctness·Answer coverage 0점, **Faithfulness는 해당 없음(N/A)** |
| 7 힌트 | 스크립트가 뽑은 주된 값과 답변에 없는 값을 참고용으로 제공 |

## 집계 규칙 (점수를 평균낼 때)

- **거부 답변의 Faithfulness는 평균과 쌍체 비교에서 뺀다.** 거부 판정은 `claude_judge.is_refusal`(`확인되지 않`, `찾을 수 없`, `근거 부족`, `정보가 없` 문구)이고, `grid_report.load_scores`가 그 항목의 Faithfulness를 `None`으로 둔다. 분모가 그만큼 줄어든다.
- **표에는 항상 `거부 N건 제외`를 Faithfulness 옆에 적는다**(`grid_report.summary_table`). 거부를 많이 하는 시스템의 Faithfulness가 부풀려 보이는 선택 편향을 독자가 가늠할 수 있게 하기 위해서다. 거부는 Correctness와 Answer coverage에서 이미 0점을 받으므로 Faithfulness에서 한 번 더 벌주지 않는다(0점으로 넣으면 "환각"과 "답을 못 냄"이 한 숫자에 섞인다).
- `scripts/run_experiment.py evaluate`의 `summary.json` 평균에는 이 제외를 적용하지 않는다. 보고하는 표는 `scripts/grid_report.py` 기준이다.
- 라운드가 다른 점수를 비교할 때는 같은 루브릭 버전끼리만 비교한다. 이전 라운드(v1) 점수는 `judge_cache_v1_ref/`에 보존돼 있다(재채점 후).

## 사용법

```bash
# 내보내기: 저장된 답변을 시스템 식별 없이 섞어 배치로 (기본 --rubric v2)
python scripts/claude_judge.py export --runs <run-id>:<system> [<run-id>:<system> ...] --out-dir eval_resources/claude_judge/<round> [--batch-size 10] [--seed N] [--rubric v1|v2]
# 서브에이전트가 <round>/rubric.md를 읽고 batches/batch_NN.json을 채점해 results/batch_NN.json을 쓴다
# 가져오기: 검증(빠진 항목, 0~5 정수) 후 judge_cache로 옮긴다. v2 재채점이면 이전 캐시는 judge_cache_v1_ref/에 남는다
python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/<round>
# 보고서: 칸별 평균, 쌍체 비교, 칸별 답변 부록
python scripts/grid_report.py --run-id <run-id> --summary-out <path> --answers-out <path>
```

## 루브릭 전문 (v2, 서브에이전트가 읽는 `rubric.md`)

# 채점 지시 (루브릭 v2)

아래 루브릭으로 배치 파일의 항목을 하나씩 채점한다. 항목마다 질문, 기대 답변, 검색된 컨텍스트, 생성된 답변, 힌트(`hint`)가 있다.

- 항목의 출처(어느 시스템·실행인지)는 알려지지 않았고 알려고 하지 않는다. 항목끼리 비교하지 말고 각 항목을 루브릭에만 비추어 독립적으로 채점한다.
- 점수는 0~5 정수. 4개 축(correctness, answer_coverage, faithfulness, context_relevance) 모두, 각각 한 문장 근거(reason)를 쓴다. 아래 규칙을 적용했으면 근거에 규칙 번호를 적는다(예: "규칙2").
- Faithfulness와 Context Relevance는 항목의 `context` 필드만 기준으로 한다. 외부 지식으로 답이 맞는지 추측하지 않는다.
- 결과는 JSON 파일 하나로 쓴다: `{"<item_id>": {"correctness": {"score": 0, "reason": "..."}, "answer_coverage": {...}, "faithfulness": {...}, "context_relevance": {...}}, ...}`.
  배치의 모든 item_id가 빠짐없이 들어 있어야 한다.

## 판정 규칙 (라운드가 달라도 같은 기준을 쓰기 위한 명시 규칙)

1. **주된 값.** 기대 답변에서 괄호 밖에 있는 값·사실이 주된 값이다. 괄호 안의 내역(추정가격, 부가가치세, 동복·하복 금액, 구성 항목)은 부차 정보다. 괄호 밖에 값이 하나도 없을 때만 괄호 안 값을 주된 값으로 본다.
2. **Correctness.** 주된 값만으로 판단한다. 주된 값이 모두 맞으면 부차 정보가 빠지거나 달라도 5점이다. 주된 값 하나가 틀리거나 빠지면 최대 3점(값이 여럿이면 맞은 비율로), 핵심 값이 틀리면 0~2점이다.
3. **Answer coverage.** 주된 값(사실 포인트)이 답변에 모두 들어 있는가만 본다. 부차 정보(괄호 안 내역) 누락은 감점하지 않는다. 주된 포인트 일부가 빠지면 빠진 비율대로 낮춘다. 모두 있으면 5점이다.
4. **표기와 라벨.** (a) 숫자 표기 차이(쉼표, `원`, 공백, `약 …억`과 정확한 값의 병기, `5천만 원`=`50,000,000원`)는 같은 값이다. (b) 질문이 묻는 금액 이름(기초금액, 추정금액, 사업예산, 사업금액, 예산)과 답변이 쓴 이름(예: 사업비)이 달라도 값이 기대 주된 값과 같으면 감점하지 않는다.
5. **비교 질문**(어느 쪽이 더 큰가). 주된 사실은 선택한 대상(과 있으면 그 값)이다.
6. **답변 거부**(`문서에서 확인되지 않습니다` 등, `hint.refusal`이 true인 항목). Correctness와 Answer coverage는 0점이다. Faithfulness는 주장이 없어 채점 대상이 아니므로 해당 없음(N/A)이다. 점수 칸에는 0을 쓰고 근거를 `N/A(거부 답변)`으로 시작한다. 집계는 이 항목의 Faithfulness를 평균에서 뺀다. Context Relevance는 context만 본다.
7. **힌트.** `hint.primary_values`는 스크립트가 기대 답변에서 뽑은 주된 값 후보이고 `hint.missing`은 그중 답변에 문자열로 없는 값이다. 문자열 일치 힌트일 뿐이다. 표기 차이나 환산으로 같은 값이면 `missing`이어도 맞다고 보고, 문자열이 있어도 엉뚱한 맥락이면 틀리다고 본다.

---

당신은 RAG(Retrieval-Augmented Generation) 시스템의 응답 품질을 평가하는 전문 심사관입니다.

주어진 정보를 바탕으로 아래 4가지 기준을 각각 0~5점으로 채점하고, 각 점수에 대한 1줄 근거를 작성하세요.

## 채점 기준

### Correctness (정확성)
생성된 답변이 기대 답변과 의미적으로 일치하는 정도. 포함된 정보가 정확한가에 초점.
- 5: 기대 답변의 핵심 정보를 모두 정확히 포함
- 4: 대부분의 핵심 정보가 정확하나 사소한 부정확 있음
- 3: 핵심 정보의 절반 정도가 정확
- 2: 일부만 맞고 오류 포함
- 1: 거의 관련 없는 답변
- 0: 완전히 틀리거나 답변 거부

### Answer Coverage (답변 커버리지)
기대 답변의 핵심 정보가 생성 답변에 얼마나 누락 없이 포함되었는가. Correctness와 달리 빠진 정보가 있는가에 초점.
- 5: 기대 답변의 모든 핵심 포인트를 빠짐없이 포함
- 4: 대부분 포함하나 사소한 항목 1~2개 누락
- 3: 핵심 포인트의 절반 정도만 커버
- 2: 주요 정보 대부분 누락, 일부만 언급
- 1: 핵심 정보가 거의 없음
- 0: 관련 정보 전혀 없음 또는 답변 거부

### Faithfulness (충실성)
생성된 답변이 검색된 context에 근거하고 있는 정도 (환각 없는 정도).
- 5: 답변의 모든 내용이 context에서 직접 확인 가능
- 4: 대부분 context에 근거하나 사소한 추론 포함
- 3: 핵심은 context에 있으나 상당한 추론/일반화 포함
- 2: context와 부분적으로만 관련, 환각 포함
- 1: 대부분 환각이거나 context와 무관
- 0: 완전한 환각 또는 context 무시

### Context Relevance (검색 관련성)
검색된 context가 질문에 실제로 관련 있는 정도.
- 5: context가 질문에 완벽히 관련, 답변에 필요한 정보를 충분히 포함
- 4: 대부분 관련 있으나 일부 불필요한 내용 포함
- 3: 부분적으로 관련, 핵심 정보가 일부 부족
- 2: 관련성이 낮고 대부분 무관한 내용
- 1: 거의 관련 없는 문서
- 0: 완전히 무관한 문서

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. 마크다운 코드블록(```)이나 다른 텍스트 없이 순수 JSON만 출력하세요.
reason은 반드시 한 문장으로 작성하세요.

{"correctness": {"score": 0, "reason": "..."}, "answer_coverage": {"score": 0, "reason": "..."}, "faithfulness": {"score": 0, "reason": "..."}, "context_relevance": {"score": 0, "reason": "..."}}
