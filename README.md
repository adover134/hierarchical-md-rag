# hierarchical-md-rag

한국 공공기관 입찰공고문(HWP/HWPX/PDF)을 검색·질의응답하는 RAG 파이프라인이다.
**팀 프로젝트(AI_7-team)의 실제 RAG 파이프라인을 포크**해서, HWP/HWPX 문서를
markdown으로 변환하는 파싱 단계만
[`hwp-hierarchical-md-skill`](https://github.com/adover134/korean_official_document_parser_skill)로
교체한 것이다 — 기존의 "HWP→PDF→markdown" 변환 체인을 완전히 대체하며, 그 이전
단계들이 만들던 청킹/검색/답변 생성 로직은 원본 그대로 재사용한다. PDF 원본
문서는 팀의 기존 파이프라인을 그대로 쓴다(새 파서는 HWP/HWPX 전용).

> **비공개 저장소다.** 원본 팀 프로젝트를 credit해서 포크한 것이므로, 전 팀원의
> 동의를 받기 전까지는 공개하지 않는다. 이 문서도 그 전제 위에서 작성됐다.

## 구조

- `src/graph/workflow.py` — `RAGChatbotV17`, 질의 분석·검색·답변 생성을 orchestrate
- `src/parsers/` — 청킹(`chunker.py`), 헤더 감지(`auditor.py`), HWP/PDF 로더
- `src/retrievers/` — 벡터스토어(`vectorstore.py`), DB 구축(`build_db.py`), 검색
  휴리스틱(`query_heuristics.py`), 결과 후처리(`result_postprocess.py`)
- `src/evaluation/` — recall/MRR 지표(`metrics.py`), LLM-as-Judge(`llm_judge.py`)
- `scripts/parser_bridge.py` — 새 skill 파서를 팀 파이프라인에 연결하는 통합 지점
  (재매핑 없이 완전 대체 — 상세는 파일 내 docstring 참고)
- `scripts/build_index_new_parser.py` / `scripts/index_pdf_originals.py` — DB 구축
- `scripts/api.py` — 검색(질의응답) API. UI가 실제로 붙는 지점은 이거 하나뿐 —
  DB 구축은 위 스크립트를 서비스 제공자가 직접/자동화로 돌리는 별개 작업(CLI 전용,
  API로 노출하지 않음)
- `scripts/eval_retrieval.py` — E2E 평가(검색 recall + LLM-as-Judge 4축 채점)
- `docs/BUGFIXES.md` / `docs/BUGFIXES_PLAIN.md` — 버그 수정 기록(상세/쉬운 설명)

## DB 구축

```bash
python scripts/build_index_new_parser.py --input <HWP/HWPX_폴더>   # 새 파서 경로
python scripts/index_pdf_originals.py --input <PDF_폴더>            # 팀 원본 경로
```

두 스크립트 다 `data_index/`(gitignore됨)에 동일한 Chroma 컬렉션으로 upsert한다.
임베딩은 로컬 모델(`jhgan/ko-sroberta-multitask`, dense) + BM25(sparse, Kiwi
형태소 분석 기반)를 함께 쓰는 하이브리드 인덱스라 별도 API 키가 필요 없다.

## 답변 생성 LLM 설정

`.env`(gitignore됨)에 아래 값을 채운다:

```bash
HWP_RAG_LLM_BASE_URL=https://api.groq.com/openai/v1   # 또는 http://localhost:11434/v1 (Ollama)
OPENAI_API_KEY=<groq api key 또는 로컬이면 아무 문자열>
REASONING_MODEL=openai/gpt-oss-20b                      # Ollama면 gpt-oss:20b
QUERY_INTENT_MODEL=openai/gpt-oss-20b
```

Groq 무료 한도(일일 200,000 토큰)를 소진하면 로컬 Ollama로 즉시 전환 가능하다
— **반드시 같은 모델(`gpt-oss:20b`)을 써야 결과가 비교 가능하다**(다른 모델,
특히 VLM 계열은 이 파이프라인의 2단계 프롬프트에 안 맞아 결과가 왜곡될 수
있음, `docs/BUGFIXES_PLAIN.md` 참고). 로컬은 응답이 느려서(질문당 1~2분)
타임아웃을 넉넉히 잡아야 한다:

```bash
ollama pull gpt-oss:20b
HWP_RAG_LLM_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama-local \
REASONING_MODEL=gpt-oss:20b QUERY_INTENT_MODEL=gpt-oss:20b OPENAI_TIMEOUT_SEC=1200 \
python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset_new8.yaml --judge_model gpt-oss:20b
```

`gpt-oss:20b` 정도 크기의 로컬 reasoning 모델은 검색(retrieval)이 완벽해도
답변 생성 단계에서 실행마다 결과가 달라질 수 있다 — 동일한 컨텍스트에
정답이 명확히 들어있는데도 어떨 때는 정확히 답하고 어떨때는 "확인되지
않습니다"로 놓치는 사례가 확인됐다(`docs/BUGFIXES.md`의 "다른 모델로
m2/m19 교차검증" 참고, 같은 컨텍스트를 OpenAI/Claude로 재현하면 매번
정답). retrieval 관련 회귀를 진단할 때 recall@k가 이미 만점인데 correctness만
낮다면, 먼저 리트리벌 코드가 아니라 이 모델 자체의 편차를 의심할 것.

### 답변 생성 방식: 기본은 순수 LLM

정규식으로 값을 뽑아 템플릿에 끼워넣는 규칙 기반 추출 계층이 원본에 있었지만,
`eval_dataset_new8.yaml`로 직접 비교해본 결과 **LLM이 검색된 컨텍스트만 보고
직접 답변을 생성하는 쪽이 correctness/coverage 모두 더 높게 나왔다**(규칙 기반
템플릿·근거검증 둘 다 자체적으로 취약한 키워드 휴리스틱에 의존하고 있었음 —
자세한 원인은 `docs/BUGFIXES.md` 참고). 그래서 **기본값은 순수 LLM 생성**이다.
규칙 기반 계층은 코드는 그대로 남겨뒀고, 비교/디버깅용으로만 아래처럼 되살릴
수 있다:

```bash
HWP_RAG_ENABLE_LEGACY_EXTRACTIVE=1 python ...
```

## 검색 API

`RAGChatbotV17.answer()`를 HTTP로 노출하는 질의응답 전용 API(`scripts/api.py`,
FastAPI + `uvicorn`, `langc` conda 환경에 이미 설치돼 있음). DB 구축(위 "DB 구축" 절)과는
완전히 별개다 — 이 API에는 문서 업로드/인덱싱 엔드포인트가 없고, 서비스 사용자용 UI가
붙는 지점이 여기 하나뿐이라는 게 설계 원칙이다.

```bash
python scripts/api.py --port 8001
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RAG_API_KEYS` | - | 쉼표로 구분한 허용 API 키 목록. 미설정 시 인증 없이 열린 상태로 동작(로컬 개발용) — 실제 배포 시 반드시 설정할 것 |

엔드포인트:
- `GET /v1/health` — DB/챗봇 초기화 상태 점검(인증 불필요)
- `POST /v1/query` — `{"query": "...", "top_k": 24}` -> `RAGChatbotV17.answer()`의 반환 dict
  그대로(`answer`/`evidence`/`confidence`/`retrieved_docs` 등)

```bash
curl -X POST http://localhost:8001/v1/query \
  -H "Authorization: Bearer $RAG_API_KEYS" \
  -H "Content-Type: application/json" \
  -d '{"query": "사업비가 가장 높은 공고는?", "top_k": 10}'
```

rate limit은 아직 없다(hwp-hierarchical-md-service의 rate_limit.py는 Langfuse 트레이스를
근거로 세는데, 이 저장소는 Langfuse를 아직 안 씀 — 필요해지면 추가 검토).

## 평가

```bash
python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset_new8.yaml --judge_model openai/gpt-oss-20b --label <라벨>
python scripts/build_eval_report.py --label <라벨>   # eval_resources/eval_report_<라벨>.html 생성
```

두 단계 다 팀 프로젝트(AI_7-team)와 동일한 방식이다 — `eval_retrieval.py`가
`eval_resources/eval_results_<라벨>.json`을 쓰고, `build_eval_report.py`가 그걸
읽어 HTML 대시보드로 만든다. `build_eval_report.py`는 표준 라이브러리만 써서
(`src/` 비의존) 두 저장소 어디서 돌려도 그대로 동작한다. 결과 JSON/HTML은 둘 다
gitignore됨(`eval_resources/eval_results_*.json`, `eval_resources/eval_report_*.html`).

- `eval_resources/eval_dataset_57docs.yaml`(q1~q8) — 초기 재현 케이스 중심
- `eval_resources/eval_dataset_new8.yaml`(n1~n8) — 문서/기관 겹치지 않는 신규
  세트, 문서 단위+청크 단위(`chunk_uids`) 정답 라벨 포함, 최신 상태에서 8/8 정답
- `--judge_model`은 반드시 지정할 것 — 기본값(`gpt-5-mini`)은 Groq에 없어서
  판정 자체가 실패한다

## 현재 상태

`docs/BUGFIXES.md`에 오늘까지 추적·수정한 근본원인 15개가 전부 기록돼 있다
(검색 순위 오판, org 해석 우선순위, retrieval depth, 답변 생성 방식 전환,
비교 질의 컨텍스트 불균형 등). 두 평가셋 모두 현재 전 문항 정답 상태다.
