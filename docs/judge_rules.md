# 채점기 규칙 (현재: 팀 rubric + 추가 기준 5개, v6.2 + 원본 검증)

> 이 문서에서 알게 되는 것</br>
    1. 지금 쓰는 채점 기준의 전문</br>
    2. 채점자가 받는 것과 채점 방식</br>
    3. 점수를 평균내는 방법</br>
    4. 원본 검증의 방식과 지시문
    5. 채점기의 알려진 한계

## 기준

- 채점 기준은 **팀 프로젝트의 rubric**(`src/evaluation/llm_judge.py`의 `JUDGE_SYSTEM_PROMPT`, 팀 저장소와 같다)에 **추가 기준 5개**를 붙인 것이다.
- 추가 기준은 2026-11-28에 사용자가 원문을 보고 승인했다.
- `v6.1`(2026-11-28): 추가 기준 3을 context가 쓴 이름과 Context relevance까지 넓혔다. 바꾸기 전과 후의 원문을 보고 승인받았다.
- `v6.2`(2026-11-29): 추가 기준 5를 더해 Context relevance를 기대 답변에서 context 방향으로 판단한다. 문장을 보고 승인받았다. 팀 rubric의 Context relevance 설명("일부 불필요한 내용 포함"이면 4점)보다 이 기준이 앞선다.
- **루브릭 버전**: 큰 번호는 프로젝트 버전이 바뀔 때만 올린다. 같은 프로젝트 버전(1.4) 안의 변경은 소수점 뒤를 올린다(`v6` → `v6.1`).
- **점수에 영향을 주는 것(기준 문장, 지시문, 채점 입력, 묶는 방식, 평균 계산)을 바꿀 때는 바꾸기 전과 후의 원문이나 code를 보이고 승인받는다.**

## 채점자가 받는 것

| 항목 | 내용 |
|---|---|
| 질문 | 평가 set의 질문 |
| 기대 답변 | 평가 set의 기대 답변 |
| context | 근거(evidence) + 검색 상위 5개 chunk의 머리글과 본문. 머리글은 `[공고명 - 문서 p.N] \| project=기관명`이고 답변 모델이 받는 것과 같다 |
| 생성 답변 | 저장된 답변 원문 |
| 검증 결과 | 원본 검증이 찾은 대상 공고(문서, 공고번호, 특정한 이유, 인용), 답, 확인하지 못한 것. 2026-11-28부터 넣는다 |

chunk 본문은 2026-08-24부터 넣는다. 근거만 주면 근거가 있는 답의 Faithfulness가 낮게 나와서 더했다.
머리글은 2026-11-28부터 넣는다. 본문만 주면 어느 사업의 값인지 알 수 없다는 감점이 났다.
머리글의 metadata는 DB(`data_index/chroma_B`)에서, 단축 경로의 행은 `data_index/metadata.csv`에서 읽는다.

## 채점 방식

- 생성은 local `gpt-oss:20b`, 채점은 항상 Claude(Opus)다. 별도 API 키는 쓰지 않는다. gpt-oss로는 채점하지 않는다.
- 두 단계다. 먼저 검증자가 원본에서 대상 공고와 답을 찾고, 다음에 채점자가 그 결과를 함께 받아 채점한다.
- 답을 시스템 이름 없이 섞어 10개씩 묶고, 묶음마다 호출 하나가 채점한다(`scripts/judge_grade.py`).
- **격리**: `claude -p --safe-mode --tools ""`를 빈 폴더에서 부른다. 지시 파일, memory, hook, git 상태, 도구가 붙지 않는다. 2026-11-28부터다. 그전의 subagent 채점은 지시 파일과 memory 목록도 함께 받았다.
  - Claude Code가 붙이는 계정 email과 실행 환경 정보는 남는다.
  - 호출 기록에 `claude-haiku-5-5`도 남는다. 입력은 채점 입력과 비슷한 분량이고 출력은 호출당 약 130 token이다. 용도는 확인하지 못했고, 점수는 Opus의 응답이다.
- 채점자의 system prompt는 `rubric.md` 전문 뒤에 아래를 붙인 것이다. 마지막 두 줄은 원본 검증의 지시문이다(둘째 줄은 2026-11-28에 더했다). user message는 batch 파일의 내용이다.

```text
## 채점 지시
당신은 RAG 답변 채점자다.
입력은 항목의 JSON 목록이다. 모든 항목을 위 루브릭대로 채점한다.
결과는 item_id를 키로, 값은 루브릭의 JSON 형식으로 낸다.
항목의 "검증 결과"는 원본에서 따로 확인한 것이다. 채점하기 전에 context의 문서가 검증 결과의 공고와 같은지 대조한다.
생성 답이나 context가 기대 답변과 다르게 표현돼도, 검증 결과의 값이나 원문 구절로 같은 내용임이 확인되면 맞은 것으로 본다.
```

## 원본 검증

2026-11-28부터 쓴다. 질문과 답변의 이름만 견주지 않고 원본 문서를 확인하게 하려는 것이다(2026-11-02 요청).

| 항목 | 내용 |
|---|---|
| 검증자가 받는 것 | 아래 지시문과 **질문**, 자기가 요청한 검색 결과. 생성 답, 기대 답변, 검색 context는 받지 않는다 |
| 검색 대상 | 공고 목록 엑셀의 모든 열(`scripts/judge_excel.py`, 먼저 본다)과 원본 PDF, HWP, HWPX(`scripts/judge_search.py`). 프로젝트의 parser와 DB를 거치지 않는다 |
| 호출 | `claude -p --safe-mode --tools ""`(Opus). 지시 파일, memory, 도구 없이 빈 폴더에서 부른다. 요청한 목록·검색·보기만 code가 실행한다 |
| 결과의 사용 | 문항마다 한 번 만들고, 두 방식의 채점 항목에 같은 결과를 붙인다 |
| 측정(`verify02`, 현재) | 40문항, 호출 124회, CLI가 알려준 환산 비용 $3.11(`m20` 한 문항의 재실행 포함). 특정한 문서는 40문항 모두 평가 set의 정답 문서와 같았고, 단축 경로 18문항 모두 엑셀의 `사업 금액`을 보았다 |

검증자의 지시문은 아래가 전부다.

```text
당신은 RAG 답 채점을 위한 검증자다. 아래 질문의 답을 원본에서 직접 찾는다. 공고 목록(엑셀)을 먼저 보고, 목록에 없는 내용은 원본 문서에서 찾는다.
- 질문이 가리키는 공고를 먼저 특정한다. 이름이 비슷한 공고가 여럿이면 지역, 차수, 공고번호, 본문을 대조해 하나로 좁히고 이유를 적는다.
- 근거가 된 원문 구절을 그대로 인용한다. 찾지 못하면 "확인 불가"라고 쓴다.
- "answer"에는 목록에서 확인한 값과 문서에서만 확인한 내용을 구분해 적는다.
출력: {"notices": [{"file": "", "notice_no": "", "why": "", "quotes": []}], "answer": "", "unverified": ""}

원본을 직접 열 수는 없고, 아래 행동을 한 번에 하나씩 JSON으로 요청하면 결과를 받는다.
- {"action": "excel", "query": "낱말 낱말"}: 공고 목록(엑셀)에서 낱말이 든 행. 모든 열(사업 금액 포함)을 보여준다. query가 비면 열 이름
- {"action": "docs"}: 원본 문서 목록
- {"action": "search", "query": "낱말 낱말"}: 원본 본문에서 낱말이 많이 든 부분
- {"action": "show", "doc": 문서번호, "start": 시작줄}: 원본 한 문서의 본문
- {"action": "final", "result": {위 출력 형식}}: 검증을 마치고 결과를 낸다. file에는 문서 이름을 그대로 적는다.
```

## 점수 평균

- 축마다 모든 문항(40개)의 평균이다. 거부 답변도 그대로 넣는다.
- 현재 점수는 [07 결과](07_결과.md)의 "현재 결과"에만 적는다.
- 보고하는 모든 점수 문서에 "심사: Claude(격리 호출)"과 rubric 버전을 적는다. 2026-11-28 `round24`까지의 점수는 "심사: Claude(subagent)"다.

## 사용법

```bash
# 내보내기: 저장된 답변을 시스템 식별 없이 섞어 배치로
python scripts/claude_judge.py export --runs <run-id>:<system> [<run-id>:<system> ...] --out-dir eval_resources/claude_judge/<round> [--batch-size 10] [--seed N]
# 원본 검증: 검색 자료를 만들고, 질문만으로 검증한다(질문이 바뀌지 않으면 전에 만든 결과를 다시 쓴다)
python scripts/judge_search.py build   # 원본 문서의 검색 자료. 공고 목록은 검증할 때 엑셀에서 읽는다
python scripts/judge_verify.py run --out eval_resources/claude_judge/<verify>/verification.json
# 검증 결과를 batch에 붙인다(<round>/instruction.txt도 함께 만든다)
python scripts/judge_verify.py attach --round-dir eval_resources/claude_judge/<round> --verification eval_resources/claude_judge/<verify>/verification.json
# 격리 채점: batches/batch_NN.json을 채점해 results/batch_NN.json을 쓴다(이미 있는 결과는 다시 채점하지 않는다)
python scripts/judge_grade.py --round-dir eval_resources/claude_judge/<round>
# 가져오기: 검증(빠진 항목, 0~5 정수) 후 judge_cache로 옮긴다
python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/<round>
# 평균과 팀 검색 지표. chunk label은 현재 DB에 맞춘 평가 set 사본을 준다
python scripts/run_experiment.py evaluate --run-id <run-id> --systems <system> ... \
    --chunk-labels eval_resources/retrieval/chunk_synced_new20.yaml eval_resources/retrieval/chunk_synced_new20_v2.yaml
# 이력 한 줄 추가
python scripts/eval_history.py --run-id <run-id> --commit <답변을 만든 commit> --rubric "v6.2+원본검증+격리"
```

chunk label 사본은 팀 저장소의 `scripts/sync_eval_chunk_labels.py`로 만든다(`--dataset`, `--output`, `--db-path data_index/chroma_B`, `--collection chunks`). DB를 새로 만들면 다시 만든다.

## 채점 결과를 보는 곳

- 현재 점수(생성한 답의 지표)는 [07 결과](07_결과.md)의 "현재 결과"다.
- 문항별 채점 입력과 점수, 사유는 HTML 보고서로 만든다(git 제외).

```bash
python scripts/judge_report_html.py --round-dir eval_resources/claude_judge/round26
```

## 채점기의 알려진 한계

### 실제 채점(`round26`)에서 본 것

심사: Claude(격리 호출, Opus). 점수는 [07 결과](07_결과.md)의 "현재 결과"에 있다.

- **Context relevance는 80개 모두 5점이다.** 추가 기준 5는 값이 질문 공고의 context에 있는지만 보므로, 이번 답에서는 chunk Recall@5와 겹치고 차이를 가려내지 못한다. context에 섞인 다른 내용은 재지 않는다.
- 같은 입력의 두 항목이 갈린 것은 Answer coverage 3개다.
- 남은 감점은 감점돼도 안 돼도 되는 것으로 본 유형(금액 내역·부가세 누락, 기산점 누락, "총 N기" 덧붙임)과, 맞는 감점으로 본 `m1`(원문에 없는 "예산")이다.
- 검증은 문항마다 한 번이다. 검증이 틀리면 그 문항의 채점이 함께 틀릴 수 있다.

### 추가 기준 5의 시험 (`probe_v6_2`)

**아래 점수는 답의 성능이 아니다.** 채점기 시험이다(2026-11-29, 심사: Claude(격리 호출, Opus)). `round25`의 감점 30개, context를 바꿔 넣은 8개, 값을 틀리게 바꾼 8개를 채점했다.

| 통과 기준(채점 전에 정함) | 결과 |
|---|---|
| context를 바꿔 넣은 8개: Context relevance 3점 이하 | ✅ 8 / 8 |
| 값을 틀리게 바꾼 8개: Correctness, Faithfulness 3점 이하 | ✅ 8 / 8 |
| 검색 답의 "무관한 내용" 감점 13개가 사라짐 | ✅ 13 / 13 |
| `m1`의 Correctness, Faithfulness 감점 유지 | ✅ 유지 |

### 검증 지시 문장과 격리 채점의 시험 (`probe_v6_1b`, `probe_v6_1c`)

**아래 점수는 답의 성능이 아니다.** 채점기 시험이다(2026-11-28).

| 시험 | 항목 | 채점 | 통과 기준(채점 전에 정함) | 결과 |
|---|---|---|---|---|
| `probe_v6_1b` | `round24`의 감점 21, context 바꿈 8 | subagent | 바꿈 8개 Context relevance 3점 이하, 당시 오류로 본 4개 감점 유지, 항목명 감점 0 | ✅ 통과 |
| `probe_v6_1c` | 위 29, 값을 틀리게 바꾼 8 | 격리 | 바꿈 8개 Context relevance 3점 이하, 틀린 값 8개 Correctness·Faithfulness 3점 이하, 항목명 감점 0 | ✅ 통과(틀린 값 8개는 모두 1점) |

- `probe_v6_1c`에서 같은 기관·같은 금액의 2\~3지역 context는 Faithfulness 3점이었다. 답의 값이 받은 context에 있으므로 "받은 context 기준"과는 다르다.

### 추가 기준 3 변경 시험 (`probe_v6_1`)

**아래 점수는 답의 성능이 아니다.** `round23`에서 감점된 단축 경로 13개와 context를 바꿔 넣은 8개를 `v6.1`로 채점한 채점기 시험이다(2026-11-28, 심사: Claude(subagent)).

| 묶음 | 통과 기준(채점 전에 정함) | 결과 |
|---|---|---|
| 감점됐던 13개 | Context relevance 사유에 항목명·원문 표현 요구가 없음 | ✅ 13개 모두 5점 |
| 바꿔 넣은 8개 | Context relevance 3점 이하 8 / 8 | ✅ 8 / 8 |

- 13개에는 타당한 감점으로 본 "내역 누락"만 이유였던 5개도 있었고, 이 5개도 5점이 됐다.

### 근거를 바꿔 넣은 시험

**아래 점수는 답의 성능이 아니다.** 채점기를 시험하려고 context를 일부러 바꿔 넣은 결과이며, 어떤 점수 보고에도 넣지 않는다.

저장된 답, 질문, 기대 답변은 그대로 두고 **context만 다른 공고의 것으로 바꾼** 8건과 원래 것 8건을 섞어 채점했다(2026-11-28, 심사: Claude(subagent), v6).

| 바꾼 context | 건수 | 검증 없음(`probe_wrong_doc`) F / CR | 원본 검증(`probe_verify2`) F / CR |
|---|---|---|---|
| 다른 기관, 다른 사업 | 3 | 0\~1 / 0 | 0 / 0 |
| 다른 학교의 같은 종류 공고 | 1 | 1 / 1 | 0 / 1 |
| 같은 기관, 다른 금액 | 1 | 2 / 2 | 1 / 1 |
| 값이 같은 다른 사업(전기와 건축) | 1 | 3 / 3 | 2 / 2 |
| 1지역 질문에 같은 기관, 같은 금액의 2\~3지역 공고 | 2 | 5 / 5 | 5 / 2 |

- 검증이 없으면 **지역 번호만 다른 공고를 걸러내지 못했다.** 원본 검증에서는 Context relevance가 2점이 됐다.
  답의 값과 기관명이 받은 context에 있으므로 Faithfulness 5점은 맞는 채점이다(Faithfulness는 받은 context 기준).
- 원본 검증에서 바꾼 8건의 Context relevance는 두 번의 시험(`probe_verify`, `probe_verify2`) 모두 3점 이하였다.
- 원래 context 8건 중 네 축 모두 5점인 것은 검증 없음 7건, 원본 검증 첫 번째 5건, 두 번째 7건이다. 두 번의 시험은 입력이 같다.

## rubric 전문 (v6.2, `rubric.md`)

````text
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

## 추가 기준
1. Correctness는 기대 답변의 주된 값(괄호 밖의 값과 사실)으로 판단한다.
   괄호 안의 값이 빠지거나 달라도 Correctness를 깎지 않는다.
   괄호 밖의 값과 사실은 모두 있어야 한다.
2. 비교 질문의 답은 비교 결과다. 비교의 근거가 된 값이 답변에 없어도
   Correctness와 Answer coverage를 깎지 않는다.
3. 질문이 묻는 금액의 이름과 답변이나 context가 쓴 이름이 달라도(예: 기초금액을 사업비로)
   값이 같으면 Correctness, Answer coverage, Context relevance를 깎지 않는다.
4. 질문에 적힌 사업 이름과 context의 공고명이나 문서 이름이 달라도, 그것만으로 다른 문서나 다른 사업이라고
   판단하지 않는다. 답변이 문서나 context의 공고명, 기관명을 쓴 것도 감점하지 않는다.
   공고명 말고도 다른 문서임을 보여 주는 내용(질문과 다른 기관, 질문과 무관한 본문)이 있으면 그 내용으로 판단한다.
   이 기준은 네 축 모두에 적용한다.
5. Context relevance는 기대 답변에서 context 방향으로 판단한다.
   질문의 공고(검증 결과의 공고)에서 온 context에 기대 답변의 주된 값(괄호 밖의 값과 사실)이 있으면 5점이고,
   함께 있는 다른 내용은 깎지 않는다. 확인되지 않는 정도에 따라 깎는다.
   다른 공고의 context는 값이 같아도 인정하지 않는다.
````
