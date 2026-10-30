# 성능 비교 실험

팀 프로젝트 최종 RAG와 이 저장소의 두 가지 답변 방식을 **같은 문서·같은 평가셋·같은 로컬 LLM**으로 측정해
비교한다. 설정은 [`experiments/config.yaml`](experiments/config.yaml), 실행기는
[`scripts/run_experiment.py`](scripts/run_experiment.py)이다.

| 시스템 | 설명 |
|---|---|
| **팀 최종 RAG** (`team_final`) | [`adover134/RAG_project`](https://github.com/adover134/RAG_project) `main` — 코드 무수정 |
| **현 버전 기본** (`current_default`) | 이 저장소, `HWP_RAG_ANSWER_STRATEGY=two_stage` |
| **현 버전 멀티에이전트** (`current_multi_agent`) | 이 저장소, `HWP_RAG_ANSWER_STRATEGY=multi_agent` (DB는 기본과 공유) |

## 비교 조건 (공정성)

- **문서만 동일, DB는 각자 방식**: 같은 57개 문서(hwp 24 · hwpx 18 · pdf 15)를 팀 버전은 팀 파이프라인으로,
  현 버전은 새 파서(HWP/HWPX)·팀 원본 PDF 경로로 각각 색인한다. 현 버전 두 방식은 DB를 공유한다.
- **같은 엑셀 입력**: `입찰공고목록_20260808_20260809.xlsx` 한 파일을 모두에 넣는다(공고명이 문서 파일명과 57/57 일치).
  팀 버전은 자기 스키마(`data_list.csv`)로 변환해 읽고(엑셀에 없는 금액·요약·본문 컬럼은 빈 값), 현 버전은
  문서 존재 판정에 같은 엑셀을 읽는다(`src/utils/bid_list_xlsx.py`).
- **LLM은 전부 로컬 `gpt-oss:20b`**: 답변·질의의도·Judge, 그리고 파서 skill의 헤더 판단(Pass1b)까지. 팀 코드는
  `OPENAI_BASE_URL` 환경변수로 같은 로컬 엔드포인트를 쓴다(코드 수정 없음). skill은 Ollama 전용 백엔드가
  아니라 문서화된 OpenAI 호환 백엔드(`--backend openai --base-url http://localhost:11434/v1`)로 호출한다.
- **같은 평가셋·같은 top_k(5)**: 저장소의 기존 평가셋을 수정 없이 사용한다(아래). 팀 기본 top_k는 10이지만 평가에서는 5로 통일했다.
- **채점은 한 곳에서**: 질의 실행만 시스템별 프로세스에서 하고, Judge와 모든 지표는 이 저장소의 코드로 계산한다.
- **팀 파이프라인의 hwpx**: 팀 전처리기는 `.hwp`만 PDF로 바꾸고 `.hwpx`는 처리하지 않는다. 코드를 고치지 않고,
  팀이 쓰는 것과 같은 LibreOffice(`soffice`)로 hwpx 18건을 먼저 PDF로 바꿔 입력 폴더에 넣는다.

## 평가셋

| 이름 | 파일 | 문항 | 용도 |
|---|---|---|---|
| `new20` | `eval_resources/eval_dataset_new20.yaml` (m1~m20) | 20 | 기존 문항 |
| `new20_v2` | `eval_resources/eval_dataset_new20_v2.yaml` (n1~n20) | 20 | 팀 프로젝트 당시 쓰지 않은 신규 문항(일반화) |

`new8`, `57docs`는 config에서 `enabled: true`로 켤 수 있다(기본 꺼짐). 평가셋 파일은 수정하지 않는다 —
정답 핵심값은 `expected_answer`에서 자동 추출하고, 회귀·수치 비교 태그는 config에 둔다.

## 지표

| 그룹 | 지표 | 측정 방법 |
|---|---|---|
| 검색 | Context Hit Rate@3/@5 | 정답 핵심값(금액·일수·날짜 등)이 상위 K 검색 텍스트에 **모두** 있는 문항의 비율. 핵심값이 추출되는 문항만 대상(N 병기) |
| 검색 | 핵심값 MRR / 문서 단위 MRR | 핵심값이 처음 모두 확보된 순위의 역수 평균 / 정답 문서가 처음 나온 순위의 역수 평균 |
| 검색 | Header Context Inclusion | 상위 K 청크 중 대분류·중분류(`section_level1/2`) 메타데이터가 보존된 비율 |
| 파싱·청킹 | 색인된 문서 수, 청크 수·길이, 섹션 메타데이터 보유 청크 비율 | DB 전체 청크 덤프 기준 |
| 파싱 | 표 데이터 정합률 | [`experiments/table_samples.yaml`](experiments/table_samples.yaml)의 정답 `라벨: 값` 쌍이 해당 문서 청크에 그대로 존재하는 비율 |
| 파싱 | 구조 회귀 통과율 | 과거에 틀렸다가 고친 문항(config `tags.regression`)의 Correctness ≥ 4 비율 |
| 답변 | Correctness (1~5) | LLM Judge. 전체 / 기존 문항 / 신규 문항(일반화) 분리 |
| 답변 | 수치 비교 정확도 | 수치 비교 문항(config `tags.numeric_compare`)에서 기대 값·승자를 문자열로 판정(LLM 미사용) |
| 비용 | API 비용 | 모든 호출이 로컬 엔드포인트인지 확인한 결과(원격이면 `-`) |
| 비용·지연 | 단계별 소요 시간 | 색인(문서당·전체), 질의 분석·검색·근거 추출·답변 생성·전체(질의당 초) |

청크 ID는 DB마다 달라서 청크 단위 Recall은 시스템 간 비교에서 제외했다.

## 직접 실행하기

사전 준비 (한 번만):

```bash
# 1) 저장소 3개를 같은 폴더(예: ~/project/) 아래에 둔다
cd ~/project
git clone https://github.com/adover134/RAG_project.git                          # 팀 프로젝트 최종 RAG
git clone https://github.com/adover134/korean_official_document_parser_skill.git  # 문서 로딩(HWP/HWPX → Markdown) skill
#   (skill을 다른 위치에 두면 HWP_SKILL_DIR 환경변수로 알려준다)

# 2) Python 환경(langc) — LibreOffice(soffice)와 node(npx → kordoc, 최초 실행 때 자동 다운로드)도 필요하다
conda activate langc
pip install -r requirements.txt

# 3) Ollama 서버를 **컨텍스트 길이를 키워서** 띄우고 모델을 받는다(다른 터미널)
OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_NUM_PARALLEL=1 ollama serve
ollama pull gpt-oss:20b
```

> **3)의 `OLLAMA_CONTEXT_LENGTH`를 빼면 안 된다.** Ollama의 OpenAI 호환 엔드포인트(`/v1`)는 요청마다 컨텍스트
> 크기를 지정할 수 없어 기본 4096토큰으로 동작한다. gpt-oss:20b는 추론 토큰까지 그 안에서 쓰므로, 프롬프트가
> 조금만 길어도 응답이 중간에 잘려 본문이 비고(`finish_reason: length`), 파서가 `JSONDecodeError: Expecting
> value`로 실패한다. 질의 단계의 답변·Judge 호출도 같은 `/v1`을 쓰므로 같은 설정이 필요하다.

문서는 `RAG_프로세스_테스트_데이터_원본/`(저장소 루트, git 추적 안 함)에 있어야 한다.

전체 실행(입력 준비 → DB 구축 → 질의 → 채점 → 표):

```bash
python scripts/run_experiment.py all --run-id main1
```

단계별 실행(중간에 멈춰도 같은 `--run-id`로 이어서 실행한다):

```bash
python scripts/run_experiment.py prepare  --run-id main1   # hwpx→PDF 사전 변환, 엑셀 배치
python scripts/run_experiment.py build    --run-id main1   # 시스템별 DB 구축(오래 걸림)
python scripts/run_experiment.py dump     --run-id main1   # DB 청크 덤프
python scripts/run_experiment.py query    --run-id main1   # 질의 실행(원시 결과)
python scripts/run_experiment.py evaluate --run-id main1   # Judge·지표 채점
python scripts/run_experiment.py report   --run-id main1 --write   # 표 출력 + 아래 결과 절 갱신
```

자주 쓰는 옵션:

```bash
--systems team_final current_default      # 일부 시스템만
--limit 3                                  # 데이터셋별 앞 3문항만(드라이런)
--repeat 3                                 # 같은 문항 3회 반복(비결정성 편차 확인)
--config experiments/config.yaml           # 다른 설정 파일
```

결과 파일은 `eval_resources/experiment_runs/<run-id>/`(git 추적 안 함)에 쌓인다: `<system>_raw.json`(원시 응답),
`<system>_chunks.json`(DB 덤프), `<system>_build.json`(색인 시간), `summary.json`(지표·문항별 점수).

## 실행 기록과 겪은 문제 (재현 시 참고)

실험을 처음 돌릴 때 실제로 막혔던 지점과 해결을 순서대로 남긴다. 같은 환경에서는 위 "직접 실행하기"만 따르면
되고, 아래는 왜 그렇게 설정했는지의 근거다.

| 단계 | 상황 | 원인 | 조치 |
|---|---|---|---|
| prepare | 팀 전처리기는 `.hwpx`를 처리하지 않음 | `preprocessor.py`가 `.hwp`만 PDF로 변환 | 팀 코드는 그대로 두고 hwpx 18건을 LibreOffice로 먼저 PDF 변환(`prepare`가 자동 수행) |
| build(팀) | 57/57 성공, 약 898초 | — | 문서별 시간은 `<run-id>/team_final_build.json` |
| build(현재) | HWP/HWPX 42건 전부 실패 | ① 이 저장소의 변환 호출이 예전 `hwp2md` 명령(서비스 패키지, 로컬의 editable 설치 경로가 사라져 있었음)에 의존 ② 실행기가 실패를 "색인 완료"로 보고 | 변환을 **파서 skill의 `run_pipeline.py` 직접 호출**로 교체(`scripts/parser_bridge.py`, 위치는 `HWP_SKILL_DIR`). 실행기는 성공 건수가 코퍼스 문서 수와 다르면 오류로 중단하도록 수정 |
| build(현재) | skill을 gpt-oss:20b로 돌리면 `JSONDecodeError: Expecting value: line 1 column 1` | skill 기본 백엔드(`--backend ollama`)는 Ollama 네이티브 `/api/chat`에 `think:false`+`format:json`을 보내는데 gpt-oss는 이를 따르지 않고 빈 응답을 돌려줌 | skill 문서(SKILL.md)의 OpenAI 호환 백엔드 사용: `--backend openai --base-url http://localhost:11434/v1 --api-key ollama-local` |
| build(현재) | 위 백엔드로도 같은 오류 | Ollama `/v1` 기본 컨텍스트 4096토큰 — 실측: `prompt_tokens 4050 + completion_tokens 46 = 4096`, `finish_reason: length`, 본문은 비고 추론(reasoning)만 채워짐 | `OLLAMA_CONTEXT_LENGTH=32768`으로 Ollama 서버를 재기동 |

원인을 확인한 방법(재현 가능):

```bash
# 컨텍스트가 모자랄 때: finish_reason이 length이고 prompt+completion이 4096에 걸린다
curl -s localhost:11434/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"gpt-oss:20b","messages":[{"role":"user","content":"..긴 프롬프트.."}],"max_tokens":4000,"response_format":{"type":"json_object"}}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['choices'][0]['finish_reason'], d['usage'])"

# skill 단독 검증(문서 1건, 로컬 gpt-oss:20b, 약 2분): 헤더(##/###)가 삽입된 Markdown이 나와야 한다
python ~/project/korean_official_document_parser_skill/scripts/run_pipeline.py \
  "RAG_프로세스_테스트_데이터_원본/2026년 임도구조개량사업_충청북도 영동군.hwpx" \
  --pipeline-root /tmp/skill_probe --model gpt-oss:20b \
  --backend openai --base-url http://localhost:11434/v1 --api-key ollama-local -o /tmp/skill_probe/out.md
```

단독 검증 결과(2026-10-31, RTX 4060 8GB 노트북): 후보 19개 중 헤더 15개 적용(`main_section` 2, `sub_section` 13), 약 2분.
현 버전 색인은 hwp/hwpx 42건 × 문서당 수 분(GPU가 8GB라 모델이 CPU로 일부 오프로딩됨)이라 전체 한 시간 이상 걸린다.

주의: `pkill -f "ollama serve"`처럼 명령줄 패턴으로 프로세스를 끄면 그 패턴을 포함한 자기 셸까지 종료될 수 있다. 서버를
재기동할 때는 `pgrep -x ollama`로 PID를 확인해 `kill <PID>` 하는 편이 안전하다.

## 실험 결과

<!-- RESULTS:BEGIN -->
(아직 실행하지 않음 — 실행 후 `report --write`가 이 절을 채운다)
<!-- RESULTS:END -->

## 한계와 주의

- **Judge도 gpt-oss:20b**라 자기 평가 편향이 있을 수 있다. 세 시스템에 같은 Judge를 쓰므로 상대 비교는 유효하지만
  절대 점수를 다른 Judge의 점수와 직접 비교하면 안 된다.
- `temperature=0.0`이어도 로컬 모델은 실행마다 결과가 달라질 수 있다(이 프로젝트에서 실측됨). 한 번 실행한 결과는
  편차 범위 안에서 해석해야 하며, `--repeat`로 반복해 평균과 편차를 확인할 수 있다.
- 팀 버전은 엑셀에 금액·요약·본문이 없어서 CSV 기반 단축 경로(금액류 질의의 즉답)가 쓰일 수 없다. 팀 버전이
  원래 받던 `data_list.csv`와 입력이 다른 조건이다.
- 핵심값은 `expected_answer`의 숫자·날짜만 대상으로 하므로, 숫자가 없는 정답(예: 낙찰 방식)은 Context Hit 지표에서 제외된다.
- 이 노트북(GPU 8GB)에서는 gpt-oss:20b가 VRAM을 넘어 느리다. 전체 실행은 수 시간 걸릴 수 있다.
