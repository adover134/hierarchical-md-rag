# 채점기 규칙 (현재: 팀 rubric + 추가 기준 4개, v6)

> 이 문서에서 알게 되는 것</br>
    1. 지금 쓰는 채점 기준의 전문</br>
    2. 채점자가 받는 것과 채점 방식</br>
    3. 점수를 평균내는 방법</br>
    4. 아직 구현하지 않은 것

## 기준

- 채점 기준은 **팀 프로젝트의 rubric**(`src/evaluation/llm_judge.py`의 `JUDGE_SYSTEM_PROMPT`, 팀 저장소와 같다)에 **추가 기준 4개**를 붙인 것이다.
- 추가 기준은 2026-11-28에 사용자가 원문을 보고 승인했다.
- **점수에 영향을 주는 것(기준 문장, 지시문, 채점 입력, 묶는 방식, 평균 계산)을 바꿀 때는 바꾸기 전과 후의 원문이나 code를 보이고 승인받는다.**

## 채점자가 받는 것

| 항목 | 내용 |
|---|---|
| 질문 | 평가 set의 질문 |
| 기대 답변 | 평가 set의 기대 답변 |
| context | 근거(evidence) + 검색 상위 5개 chunk의 머리글과 본문. 머리글은 `[공고명 - 문서 p.N] \| project=기관명`이고 답변 모델이 받는 것과 같다 |
| 생성 답변 | 저장된 답변 원문 |

chunk 본문은 2026-08-24부터 넣는다. 근거만 주면 근거가 있는 답의 Faithfulness가 낮게 나와서 더했다.
머리글은 2026-11-28부터 넣는다. 본문만 주면 어느 사업의 값인지 알 수 없다는 감점이 났다.
머리글의 metadata는 DB(`data_index/chroma_B`)에서, 단축 경로의 행은 `data_index/metadata.csv`에서 읽는다.

## 채점 방식

- 생성은 local `gpt-oss:20b`, 채점은 항상 Claude subagent(Opus)다. 별도 API 키는 쓰지 않는다. gpt-oss로는 채점하지 않는다.
- 답을 시스템 이름 없이 섞어 10개씩 묶고, 묶음마다 subagent 하나가 채점한다.
- subagent에게 보내는 지시문은 아래가 전부다(`round22`는 실행하는 회차의 폴더, `NN`은 묶음 번호).

```text
당신은 RAG 답변 채점자다.
1) eval_resources/claude_judge/round22/rubric.md 를 읽는다.
2) 같은 폴더 batches/batch_NN.json 의 모든 항목을 루브릭대로 채점한다.
3) 결과를 results/batch_NN.json 에 루브릭의 JSON 형식(item_id를 키로)으로 쓴다.
위 파일 외에는 열지 않는다.
```

## 점수 평균

- 축마다 모든 문항(40개)의 평균이다. 거부 답변도 그대로 넣는다.
- 현재 점수는 [07 결과](07_결과.md)의 "현재 결과"에만 적는다.
- 보고하는 모든 점수 문서에 "심사: Claude(subagent)"와 rubric 버전을 적는다.

## 사용법

```bash
# 내보내기: 저장된 답변을 시스템 식별 없이 섞어 배치로
python scripts/claude_judge.py export --runs <run-id>:<system> [<run-id>:<system> ...] --out-dir eval_resources/claude_judge/<round> [--batch-size 10] [--seed N]
# subagent가 <round>/rubric.md를 읽고 batches/batch_NN.json을 채점해 results/batch_NN.json을 쓴다
# 가져오기: 검증(빠진 항목, 0~5 정수) 후 judge_cache로 옮긴다
python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/<round>
# 평균과 팀 검색 지표. chunk label은 현재 DB에 맞춘 평가 set 사본을 준다
python scripts/run_experiment.py evaluate --run-id <run-id> --systems <system> ... \
    --chunk-labels eval_resources/retrieval/chunk_synced_new20.yaml eval_resources/retrieval/chunk_synced_new20_v2.yaml
# 이력 한 줄 추가
python scripts/eval_history.py --run-id <run-id> --commit <답변을 만든 commit> --rubric v6
```

chunk label 사본은 팀 저장소의 `scripts/sync_eval_chunk_labels.py`로 만든다(`--dataset`, `--output`, `--db-path data_index/chroma_B`, `--collection chunks`). DB를 새로 만들면 다시 만든다.

## 아직 구현하지 않은 것

- **채점기가 직접 RAG로 확인하는 방식**(2026-11-02 요청): 채점자가 같은 DB에서 근거를 직접 찾아 답과 대조하는 방식이다.
  - 값이 같아도 다른 금액을 가져온 답을 지금 기준으로는 가리지 못한다.
  - 구현하기 전에 지시문과 code를 보이고 승인받는다.

## rubric 전문 (v6, subagent가 읽는 `rubric.md`)

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
3. 질문이 묻는 금액의 이름과 답변이 쓴 이름이 달라도(예: 기초금액을 사업비로)
   값이 같으면 Correctness와 Answer coverage를 깎지 않는다.
4. 질문에 적힌 사업 이름과 context의 공고명이나 문서 이름이 달라도, 그것만으로 다른 문서나 다른 사업이라고
   판단하지 않는다. 답변이 문서나 context의 공고명, 기관명을 쓴 것도 감점하지 않는다.
   공고명 말고도 다른 문서임을 보여 주는 내용(질문과 다른 기관, 질문과 무관한 본문)이 있으면 그 내용으로 판단한다.
   이 기준은 네 축 모두에 적용한다.
````
