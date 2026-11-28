# hierarchical-md-rag

공공기관 입찰공고문에서 금액, 기간, 수량 같은 값을 **질문으로 찾는** RAG 시스템이다.

[팀 프로젝트(AI_7-team)](https://github.com/Loah-Lee/AI_7-team)에서 출발했고, 문서 읽기와 표 처리, 검색, 답변, 채점을 바꿨다.

현재 버전은 **1.4.0**이다([버전과 branch](docs/08_버전과_브랜치.md)). 1.2는 `release/1.2` branch로 남겨 두었다.

## 구조 한눈에

```mermaid
flowchart LR
    H["HWP / HWPX"] -->|"parser"| M["Markdown"]
    P["PDF"] -->|"PDF loader(내장)"| M
    M -->|"DB 구축"| D[("ChromaDB")]
    D --> R["질의응답"]
    R --> API["API"]
    R --> G["Gradio 화면"]
```

## 1. DB 만들기

**입력은 Markdown 파일이다.** HWP/HWPX를 Markdown으로 바꾸는 일은 이 저장소가 아니라 parser가 한다.

**문서는 항상 [나라장터](https://www.g2b.go.kr/)에서 가져온 것이라고 가정한다.** 공고문 양식과 첨부 구성이 다른 출처의 문서는 다루지 않는다.

**metadata는 나라장터 공고목록 엑셀에서 출발한다.**
엑셀의 값을 버리지 않고 `data_index/metadata.csv`로 만들고, 엑셀에 없는 값(사업 금액 등)만 문서에서 채운다.
기관명 사전도 이 CSV에서만 만든다([metadata](docs/10_메타데이터.md)).

| Markdown을 만드는 곳 | 대상 | 비고 |
|---|---|---|
| [parser skill](https://github.com/adover134/korean_official_document_parser_skill) | HWP, HWPX | 명령줄(`run_pipeline.py`), Node(kordoc)와 LLM 필요 |
| [parser service](https://github.com/adover134/korean_official_document_parser_service) | HWP, HWPX | 같은 parser를 API/Docker로 제공 |
| PDF loader(이 저장소 내장) | PDF | `src/parsers/pdf_loader.py`, 스캔 PDF는 제외 |

입력 Markdown의 모양:

```markdown
---
title: 송림리 마을만들기사업_충청남도 서천군 농업기술센터.hwpx   ← 원본 파일 이름
---

## 1. 입찰사항           ← 대분류 (## )
### 가. 사업개요          ← 소분류 (### )
사업명: 송림리 마을만들기사업(건축,기계)

| 구분 | 금액 |            ← 표는 GFM 표. 청킹 단계에서 `라벨: 값` 줄로 풀린다
|---|---|
| 기초금액 | 285,125,000 |
```

- **파일 이름은 `공고명_기관명.md`** 형태다(문서 하나가 파일 하나).
  - DB의 `org`와 `project_name`은 `data_index/metadata.csv`에서 읽는다. CSV에 없는 파일만 이름의 첫 `_`를 기준으로 앞은 `org`, 뒤는 `project_name`으로 나눈다.
  - 이 저장소의 `org`에는 **공고명**이 들어가고, 기관명은 `project_name` 쪽이다(이름은 팀 코드에서 물려받았다).
  - 그래서 원본 HWP 파일 이름이 처음부터 `공고명_기관명`이어야 한다.
  - parser skill 혼자 돌리면 기본 출력 이름은 `<원본 파일 이름>.md`(예: `공고.hwpx.md`)이다.
  - 그래서 이 저장소 script는 `-o` 옵션으로 `output/new_parser_md/<원본 파일 이름에서 확장자를 뺀 이름>.md`에 저장한다.

- 이 저장소의 `build_index_new_parser.py`는 HWP/HWPX 폴더를 **목록으로** 받는다.
  - 문서마다 `output/new_parser_md/`에 같은 이름의 Markdown이 있으면 **parser를 다시 돌리지 않고** 그 Markdown으로 색인한다.
  - 없을 때만 skill을 호출해 만든다.

- 있는지만 파일 이름으로 확인한다.
  - parser나 kordoc 버전을 바꾼 뒤에는 `output/new_parser_md/`를 지우고 다시 만들어야 새 Markdown이 쓰인다.

순서는 **parsing → metadata → chunking과 DB**다.

```bash
# 1) Markdown 만들기 (HWP는 skill, PDF는 내장 로더. 이미 있으면 다시 만들지 않는다)
python scripts/build_index_new_parser.py --input <HWP/HWPX 폴더> --parse-only
python scripts/index_pdf_originals.py --input <PDF 폴더> --parse-only

# 2) 메타데이터: 엑셀(data_index/입찰공고목록*.xlsx)로 metadata.csv와 기관명 사전 만들기
python scripts/build_metadata.py --markdown-dir output/new_parser_md output

# 3) 청킹과 DB 구축 (2번이 없으면 멈춘다)
python scripts/build_index_new_parser.py --input <HWP/HWPX 폴더>
python scripts/index_pdf_originals.py --input <PDF 폴더>
```

결과는 `data_index/`(git 제외)에 쌓인다.

- 같은 내용의 문서를 다시 넣으면 덮어쓴다(upsert).
- 내용이 바뀐 문서는 새 문서로 취급되어 이전 chunk가 남는다.
  - parser나 kordoc 버전을 바꿔 Markdown이 달라졌다면 `data_index/chroma_B/`만 지우고 다시 만든다(같은 폴더의 `metadata.csv`와 `org_dictionary.txt`는 남긴다).

## 2. 질문하기 (두 가지 방법)

둘 다 답변용 LLM(local Ollama의 `gpt-oss:20b` 등)에 연결돼 있어야 한다.

연결 설정은 [architecture](docs/03_아키텍처.md)의 "실행하려면"을 본다.

| | API | Gradio 화면 |
|---|---|---|
| 용도 | 프로그램에서 호출 | 사람이 채팅으로 써 보기 |
| 실행 | `python scripts/api.py --port 8001` | `python scripts/gradio_app.py --port 7860` |
| 주소 | `http://localhost:8001/v1/query` | `http://localhost:7860` |
| 인증 | `.env`의 `RAG_API_KEYS`(쉼표로 여러 개, 비우면 열림) | `.env`의 `GRADIO_APP_USERNAME`, `GRADIO_APP_PASSWORD` |
| 답변 방식 | 환경변수로 선택(`two_stage` 기본, `multi_agent`) | `multi_agent`로 고정 |

```bash
# API (RAG_API_KEYS를 비웠다면 Authorization 줄은 필요 없다)
curl -X POST http://localhost:8001/v1/query -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RAG_API_KEYS의 키>" \
  -d '{"query": "송림리 마을만들기사업의 기초금액은?", "top_k": 10}'

# Gradio (외부 공개 링크가 필요하면 --share)
python scripts/gradio_app.py
```

## 3. 채점하기

답은 local 모델이 만들고 **채점은 항상 Claude**가 한다(별도 API 키 없음).
채점자는 지시 파일과 memory가 붙지 않는 격리 호출(`claude -p`)이다.
평가 도구는 `multi-agent` branch에 있다.

| 항목 | 현재 방식(1.4.0 뒤의 변경 포함) |
|---|---|
| LLM 채점 지표 | Correctness, Answer coverage, Faithfulness, Context relevance (0\~5점) |
| 채점 기준 | 팀 프로젝트의 rubric + 추가 기준 4개(`v6.1`) |
| 채점자가 받는 것 | 질문, 기대 답변, 생성 답변, context, 원본 검증 결과 |
| 원본 검증 | 질문만 받은 Claude가 공고 목록 엑셀과 원본 문서를 검색해 대상 공고와 답을 찾는다. 프로젝트의 parser와 DB는 거치지 않는다 |
| context | 답의 근거 + 검색 상위 5개 chunk. chunk마다 답변 모델이 받는 것과 같은 머리글(공고명, 문서, 쪽, 기관명) |
| 검색 지표(code 계산) | 문서 Recall@5와 nDCG@N은 모든 문항, chunk Recall@5는 chunk를 보고 만든 답만 |
| 결과 보기 | 문항별 채점 입력, 점수, 사유를 담은 HTML 보고서 |

```bash
# 저장된 답을 시스템 이름 없이 내보내기 → 원본 검증 붙이기 → 격리 채점 → 가져오기
python scripts/claude_judge.py export --runs <run-id>:<system> ... --out-dir eval_resources/claude_judge/<round>
python scripts/judge_search.py build
python scripts/judge_verify.py run --out eval_resources/claude_judge/<verify>/verification.json
python scripts/judge_verify.py attach --round-dir eval_resources/claude_judge/<round> --verification eval_resources/claude_judge/<verify>/verification.json
python scripts/judge_grade.py --round-dir eval_resources/claude_judge/<round>
python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/<round>
# 평균과 검색 지표, 이력, HTML 보고서
python scripts/run_experiment.py evaluate --run-id <run-id> --systems <system> ... \
    --chunk-labels eval_resources/retrieval/chunk_synced_new20.yaml eval_resources/retrieval/chunk_synced_new20_v2.yaml
python scripts/eval_history.py --run-id <run-id> --commit <답변을 만든 commit> --rubric "v6.1+원본검증+격리"
python scripts/judge_report_html.py --round-dir eval_resources/claude_judge/<round>
```

지시문, 채점 기준 전문, 알려진 한계는 [채점 규칙](docs/judge_rules.md)에 있다.

## 문서 읽는 순서

| 순서 | 문서 | 알게 되는 것 |
|---|---|---|
| 1 | [개요](docs/01_개요.md) | 무슨 문제를 푸는가, 팀 프로젝트와 무엇이 다른가 |
| 2 | [use case](docs/02_유즈케이스.md) | 누가 무엇을 하는가, 질문 유형 |
| 3 | [architecture](docs/03_아키텍처.md) | 구성요소와 질문 한 건의 흐름 |
| 4 | [DB 구축](docs/04_DB구축.md) | Markdown이 chunk가 되기까지, DB 구조, 다시 넣는 규칙 |
| 5 | [질의 처리](docs/05_질의처리.md) | 질문이 답이 되기까지, 검색과 답변 방식 두 가지 |
| 6 | [평가](docs/06_평가.md) | 무엇을 비교하고 점수가 무엇을 재는가 |
| 7 | [결과](docs/07_결과.md) | **현재 점수와 비용**, 믿어도 되는 범위, 이전 기록 |
| 8 | [버전과 branch](docs/08_버전과_브랜치.md) | 버전별 변화, branch 차이 |
| 9 | [용어집](docs/09_용어집.md) | 문서에 나온 말의 뜻 |
| 필요할 때 | [채점 규칙](docs/judge_rules.md) | 채점 기준 전문, 채점자가 받는 것, 알려진 한계 |
| 필요할 때 | [질의 비용 측정 방법](docs/11_비용측정.md) | 비용을 재는 방법, 요금 계산식, 개발 환경(GPU 메모리 8GB) |
| 요약 | [발표.html](docs/발표.html) | 브라우저에서 여는 슬라이드 요약(← → 키) |
| 기록 | [`EXPERIMENTS.md`](EXPERIMENTS.md) | 실험 전 과정과 측정값 |
| 기록 | [채점기 개선](docs/judge_improvement.md), [버그 수정](docs/BUGFIXES.md) | 채점과 수정의 상세 기록 |
| 기록 | [이전 README](README_이전.md) | 문서 개편 전의 README(설정, API, 평가 명령이 길게 적혀 있다) |

## 현재 결과와 한계

**현재 점수, 시간, token, 환산 요금은 [07 결과](docs/07_결과.md#현재-결과) 한 곳에만 적는다.** 다른 문서의 점수는 이전 기록이다.

- 스캔 PDF는 다루지 않는다.
- 채점 기준이 다른 버전의 점수는 서로 비교하지 않는다.
- DB 변경의 효과는 문항 40개로는 통계적으로 구분되지 않았다.

## 변경 기록

| 버전 | 바뀐 것 |
|---|---|
| 1.4.0 | 채점기: 팀 rubric + 추가 기준 4개, 채점 context에 chunk 머리글, chunk를 보지 않는 답은 chunk Recall에서 제외, 문항별 HTML 보고서. 목록 답이 잘리던 후처리를 고치고, 질의 비용 측정을 넣었다 |
| 1.3.2 | 채운 metadata를 덮어쓰지 않는다(`build_metadata.py`는 채운 값이 있으면 멈추고, build는 CSV가 있으면 metadata 단계를 건너뛴다). build 순서를 끝까지 돌려 확인했다 |
| 1.3.1 | parser(계층 추출)의 기본 모델을 `gpt-oss:20b`로 바꿨다. 전처리에서 LLM이 쓰이는 곳을 [DB 구축](docs/04_DB구축.md)에 그림으로 넣었다 |
| 1.3.0 | metadata 단계 추가(엑셀 → `metadata.csv` → 기관명 사전 → DB). DB를 다시 만들었다 |

버전별 설명은 [버전과 branch](docs/08_버전과_브랜치.md)에 있다.

## branch

`multi-agent`(GitHub 기본, 최신: multi-agent, 평가 도구, 결과 문서), `main`(`two_stage` 경로만, 같은 문서 포함).
