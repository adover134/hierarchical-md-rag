# 다음 세션 인계 문서 — 제목 반복 청크 리랭킹 버그

이 문서 하나만 읽고 바로 이어서 작업할 수 있도록 정리했다. `docs/BUGFIXES.md`/
`docs/BUGFIXES_PLAIN.md`는 이전 세션들의 상세 기록이고, 이 문서는 **지금 당장
해야 할 일**에 집중한다.

## 지금까지 상태 (전부 커밋됨, working tree 깨끗함)

최근 커밋 5개:
- `3728ab8` — `table_flattener.py`가 헤더 없는/2행 헤더 표를 잘못 읽던 버그 수정
  (m17 완전 해결, 42개 문서 재색인 완료)
- `d60ada7` — org명 "~공사" 오분류, 후속질문 컨텍스트 오염, Ollama num_ctx=4096
  기본값 3개 버그 수정
- `8f429cc`, `9c7b844`, `0b25fae` — 이전 세션의 recall/faithfulness 관련 수정들

평가셋: `eval_resources/eval_dataset_new20.yaml`(m1~m20, 이번 세션에 완전히 새로
작성). 최신 실행 라벨은 `new20_v4`(`eval_resources/eval_results_new20_v4.json`,
`eval_report_new20_v4.html`). 실행 명령:

```bash
cd /home/codeitDev/project/hierarchical-md-rag
source /home/codeitDev/miniconda3/etc/profile.d/conda.sh && conda activate langc
HWP_RAG_LLM_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama-local \
REASONING_MODEL=gpt-oss:20b QUERY_INTENT_MODEL=gpt-oss:20b OPENAI_TIMEOUT_SEC=1200 \
python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset_new20.yaml \
  --judge_model gpt-oss:20b --label <새라벨>
python scripts/build_eval_report.py --label <새라벨>
```

`new20_v4` 최종 점수: Correctness 3.90, Faithfulness 4.25, 문서 Recall@5 1.00,
청크 Recall@5 0.875. 20문항 중 실패: m3, m9(로 확인된 것과 같은 부류), m19, m20.

## 지금 당장 할 일: 제목 반복 청크 리랭킹 버그 (최우선)

### 증상

질문이 문서의 **전체 사업명/프로젝트명을 그대로 반복**하면, 그 사업명을 그대로
담고 있는 **서두 소개 청크**(실제 답이 없는)가 **정답이 담긴 다른 청크**보다
검색 순위에서 항상 이긴다. 확인된 재현 사례 3개:

1. **SRT 감속기 모터피니언 기어** — 질문: "SRT 감속기 모터피니언기어 구매
   입찰의 낙찰자 결정 기준은 무엇인가요?" → 서두 청크(`4148b8ca50e7b083_1`,
   사업명만 반복)가 실제 정답 청크(`4148b8ca50e7b083_8`, "예정가격의 82.495%
   이상...")를 top-5에서 밀어냄. (m1, eval_dataset_new20.yaml)
2. **한국마사회제주경마장 스마트워크 무선망** — 질문: "...추정금액은
   얼마인가요?" → 정답 청크("추정금액: 770,250,000원")가 top-6에 아예 없고,
   대신 무관한 적격심사 기준표 문구("...50억원 미만 10억원 이상...")를 LLM이
   답으로 착각. (m3)
3. **2026 글로벌소상공인육성사업** — 질문: "...사업예산이 더 큰 사업은
   무엇인가요?"(비교 질의) → 예산 청크(`44d53fa91300a2f6_2`, "총 사업예산:
   금150,000,000원")가 `vs.search(top_k=10)` 결과에도 없음. 서두 청크
   (`44d53fa91300a2f6_1`)가 0.864점으로 1위, 예산 청크는 순위 밖.
   **이 문항(m20)은 원래 통과했었는데(v3), table_flattener.py 수정 + 42개
   문서 재색인 이후(v4) 갑자기 깨졌다** — 이 문서 자체는 이번에 안 바뀐 문서인데,
   재색인이 코퍼스 전체 BM25 어휘 통계를 살짝 흔들면서 기존에 잠재해있던 이
   버그가 새로 발현된 것으로 확인됨. 즉 **재색인은 언제든 이 버그를 다른
   문항에서 재발시킬 수 있다** — 근본 수정이 시급한 이유.

### 원인 분석 (지금까지 확인된 것)

- `src/graph/workflow.py`의 `_score_result()`(약 10643번째 줄) — 리랭킹 스코어러.
  질의에서 뽑은 키워드가 청크 텍스트에 등장할 때마다 `+1.4`(source_key 매치는
  `+0.8`)를 더한다. 질문이 사업명 전체를 반복하면, 사업명을 그대로 담은 청크가
  키워드 10여 개를 전부 매치해서 점수가 폭발적으로 쌓인다. SRT 사례에서 직접
  확인: 서두 청크 26.5점 vs 정답 청크 8.9점.
- **더 근본적으로, `src/retrievers/vectorstore.py`의 `VectorStore.search()`
  (dense+lexical 하이브리드) 단계에서도 이미 재현된다** — `_score_result()`
  리랭커를 거치기도 전에, 원시 `vs.search()` 호출만으로도 SRT/글로벌소상공인
  사례 둘 다 정답 청크가 top-10 밖으로 밀려남. 즉 이 문제는 커스텀 리랭커
  하나만의 문제가 아니라, dense 임베딩 유사도 또는 BM25 lexical 스코어링(또는
  둘 다) 자체가 "제목을 그대로 반복하는 텍스트"에 과도한 가중치를 준다는
  뜻이다. 정확히 dense/lexical 중 어느 쪽이 주범인지, 혹은 둘 다인지는 아직
  분리해서 확인 안 했다 — `mode='chroma'`(dense만)와 `mode='hybrid'`를 따로
  호출해서 비교하면 바로 알 수 있다.

### 재현 방법

```python
from src.retrievers.vectorstore import VectorStore
vs = VectorStore()
results = vs.search('2026 글로벌소상공인육성사업 자카르타국제프리미엄소비재전 용역 사업예산',
                     top_k=10, mode='hybrid')
for r in results:
    print(r['chunk_id'], r['source'], r['score'])
# 예산이 담긴 44d53fa91300a2f6_2가 안 나온다 — 44d53fa91300a2f6_1(서두 소개)만 1위.
```

### 제안하는 접근 (아직 구현 안 함, 방향만)

- `_score_result()`의 키워드 매치 점수를 "질문에 등장하는 고유명사/프로젝트명
  토큰"과 "일반 내용 토큰"으로 구분해서, 프로젝트명 반복 자체에는 과도한
  가산점을 주지 않는 방향 검토. (다만 `_score_result()`만 고쳐도 dense/lexical
  원시 검색 단계의 편향은 안 고쳐질 수 있음 — 위 "원인 분석" 참고)
- 원시 `vs.search()` 단계 편향이 진짜 원인이라면, `_dense_score`/`_lexical_score`
  계산 방식(`src/retrievers/vectorstore.py`) 자체를 봐야 할 수도 있다.
- 즉답형 질문(사업명+구체적 필드명 조합)에 한해 "질문의 사업명 반복 여부"를
  점수에서 아예 제외하거나 감점하는 별도 처리도 고려 가능.
- 수정 전/후 반드시 SRT(m1), 스마트워크무선망(m3), 글로벌소상공인(m20) 세
  사례를 직접 재현 스크립트로 확인하고, `eval_dataset_new20.yaml` 전체 재실행
  (다른 통과 문항 회귀 여부 확인 필수 — 특히 m9, m11, m14, m15, m18처럼 이미
  잘 맞고 있는 사업명 재진술형 단일 사실 질문들이 안 깨지는지).

## 그다음 할 일: m19/m20 비교 질의 답변 생성 버그 (우선순위 낮음, 별개)

m19("장성경찰서... 건축과 통신 중 기초금액이 더 큰 공사는?")는 검색 자체는
정답 문서/청크를 둘 다 top-5~8에 정확히 포함하는데(확인됨 — 청크 데이터도
정상), LLM이 "문서에서 확인되지 않습니다"라고 답한다. 위 리랭킹 버그와는
무관 — 컨텍스트에 정답이 있는데도 비교 질의 답변 생성 경로에서 실패하는
별개 문제로 보인다. `_build_comparison_answer_from_results`
(`src/graph/workflow.py`) 근처, 또는 순수 LLM 생성 경로의 비교 질의 프롬프트를
살펴봐야 할 것 같다. 위 리랭킹 버그를 먼저 고치고 나서, m19/m20이 리랭킹
수정만으로 같이 해결되는지 먼저 확인한 뒤 착수할 것 — 별개로 밝혀지면 그때
새로 조사 시작.

## 참고

- 이번 세션에서 사용한 plan 파일(표 평탄화 버그, 완료됨):
  `/home/codeitDev/.claude/plans/effervescent-sleeping-iverson.md`
- `output/new_parser_md/`에 hwp2md 평탄화 이전 원본 마크다운이 캐싱되어 있다
  (문서별 원본 표 구조 직접 확인할 때 유용, `skip_if_exists=True`라 재색인해도
  hwp2md 재호출 없음).
- 로컬 Ollama(`gpt-oss:20b`) 20문항 1회 실행에 약 22~25분 소요.
