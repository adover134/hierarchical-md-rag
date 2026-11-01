# 성능 비교 실험

팀 프로젝트 최종 RAG와 이 저장소의 두 가지 답변 방식을 **같은 문서·같은 평가셋·같은 로컬 LLM**으로 측정해
비교한다. 설정은 [`experiments/config.yaml`](experiments/config.yaml), 실행기는
[`scripts/run_experiment.py`](scripts/run_experiment.py)이다.

| 시스템 | 설명 |
|---|---|
| **팀 최종 RAG** (`team_final`) | [`adover134/RAG_project`](https://github.com/adover134/RAG_project) `main` — 코드 무수정 |
| **현 버전 기본** (`current_default`) | 이 저장소, `HWP_RAG_ANSWER_STRATEGY=two_stage` |
| **현 버전 멀티에이전트** (`current_multi_agent`) | 이 저장소, `HWP_RAG_ANSWER_STRATEGY=multi_agent` (DB는 기본과 공유) |
| (보조) **팀 최종, CSV 단축 끔** (`team_final_no_csv`) | 위 팀 시스템과 같은 DB·코드에 `CSV_SHORTCIRCUIT_ENABLED=false`만 다름. 요청한 3개 시스템 밖의 보조 측정 — 아래 "엑셀 입력의 영향" 참고 |

## 비교 조건 (공정성)

- **문서만 동일, DB는 각자 방식**: 같은 57개 문서(hwp 24 · hwpx 18 · pdf 15)를 팀 버전은 팀 파이프라인으로,
  현 버전은 새 파서(HWP/HWPX)·팀 원본 PDF 경로로 각각 색인한다. 현 버전 두 방식은 DB를 공유한다.
- **같은 엑셀 입력**: `입찰공고목록_20260808_20260809.xlsx` 한 파일을 모두에 넣는다(공고명이 문서 파일명과 57/57 일치).
  팀 버전은 자기 스키마(`data_list.csv`)로 변환해 읽고(엑셀에 없는 금액·요약·본문 컬럼은 빈 값), 현 버전은
  문서 존재 판정에 같은 엑셀을 읽는다(`src/utils/bid_list_xlsx.py`).
- **LLM은 전부 로컬 `gpt-oss:20b`**: 답변·질의의도·Judge, 그리고 파서 skill의 헤더 판단(Pass1b)까지. 팀 코드는
  `OPENAI_BASE_URL` 환경변수로 같은 로컬 엔드포인트를 쓴다(코드 수정 없음). skill은 Ollama 전용 백엔드가
  아니라 문서화된 OpenAI 호환 백엔드(`--backend openai --base-url http://localhost:11434/v1`)로 호출한다.
- **로더 버전**: 현 버전의 HWP/HWPX 로더는 파서 skill(`korean_official_document_parser_skill`)이고 그 안에서 kordoc을 쓴다.
  재현하려면 skill 커밋과 kordoc 버전을 맞춰야 한다. `main1`은 kordoc 4.9.0으로 만들었다. 이후 skill을 kordoc **4.24.29**로 올렸다
  (skill 커밋 `07880b9`). 테두리 없는 틀 표를 4.17.0부터 글로 풀어내서, 4.9.0에서 `합계: :, 85,530,000: 100, %`처럼
  깨지던 줄이 정상이 된다. 42개 HWP/HWPX 문서에서 낱말 63,107개 중 74개가 달라졌지만 전부 서식 차이(구버전의 `1.:`·`28:` 같은 오변환,
  또는 `<sup>`/`<sub>` 태그로 감싸짐)였고 내용 누락은 없었다. 이 변경 뒤의 값은 `main1`과 직접 비교하지 않는다.
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
| 파싱 | 표 데이터 정합률 (종단) | [`experiments/table_samples.yaml`](experiments/table_samples.yaml)의 정답 `라벨: 값` 쌍이 해당 문서 청크에 그대로 존재하는 비율. 단계별 값은 아래 "표 지표" 절 |
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

## 엑셀 입력의 영향 (팀 시스템)

입찰공고목록 엑셀에는 금액·사업 요약·본문 컬럼이 없다. 팀 시스템은 원래 이 값들이 채워진 `data_list.csv`를 쓰는 CSV 단축 경로를
갖고 있어서, 변환한 CSV(해당 컬럼이 빈 값)에서는 금액류 질문에 의미 없는 답을 낸다. 드라이런(6문항)에서 확인된 예:

- 질문: "송림리 마을만들기사업(건축,기계)의 기초금액은 얼마인가요?" → 팀 답변: "사업비는 `사업비`입니다." (`csv_short_circuit: true`)

처음 계획에서는 "단축 경로가 값이 없으면 검색 경로로 넘어간다"고 가정했지만 실제로는 그렇지 않았다. 그래서 요청한 3개 시스템의
측정은 그대로 두고, 같은 팀 DB·코드에서 `CSV_SHORTCIRCUIT_ENABLED=false`만 바꾼 **보조 변형**(`team_final_no_csv`)을 함께 측정해
엑셀 입력으로 인한 영향을 분리해서 볼 수 있게 했다. 결과 표를 읽을 때 팀 시스템의 금액류 문항 점수는 이 영향이 섞여 있다.

드라이런에서 함께 관찰한 것(문항 6개, 전체 결과 아님): 팀 DB의 표 청크는 `사업명: 사업위치, 2026 년 …: 영동군 일원, Col3: …`
형태로 라벨이 뒤섞여 있다 — 이 프로젝트의 표 평탄화 수정이 겨냥한 문제와 같은 형태다.

## 표 지표: 로더 검출과 평탄화 분리

표 정합률(종단)은 **로더가 표를 표 구조로 내놨는가**와 **평탄화가 `라벨: 값`으로 풀었는가**의 합산이라 어느 단계
때문인지 알 수 없다. 두 시스템은 입력 경로부터 다르다(팀: HWPX → LibreOffice → PDF → Markdown, 현 버전: HWPX → kordoc 직접).
그래서 단계별로 나눠 잰다. DB·LLM이 필요 없고 로더 출력 파일만 있으면 된다.

| 지표 | 질문 | 정의 |
|---|---|---|
| 표 검출률 (로더) | 로더 출력에서 라벨-값 연결이 살아 있는가 | 같은 표 블록의 셀이거나, 한 줄에서 `라벨 : 값` / `값 : 라벨` / `값(라벨)`로 바로 이어짐(줄 단위, 구분자 없이 앞 항목의 값과 다음 항목의 라벨이 붙은 것은 불인정). 4자 미만 라벨·값은 셀 전체 일치만 인정 |
| 평탄화·정리 정합률 | 검출된 표가 평탄화(`step2`)와 텍스트 정리(`step2b`) 뒤에도 `라벨: 값`으로 남는가 | 검출된 쌍만 분모. 각 시스템이 **자기** 평탄화 코드를 자기 로더 출력에 적용 |
| 종단 정합률 | 최종 청크에 `라벨: 값`이 남는가 | 검출 여부와 무관한 전체 쌍 기준. 현 버전은 캐시된 로더 출력을 재청킹(DB 미사용), 팀은 청크 덤프 |

```bash
# 로더 출력(skill의 Markdown, 팀의 step1_parsed)이 이미 있어야 한다. --tag는 결과 파일 이름에 붙는 꼬리표다.
python scripts/run_experiment.py parsing --run-id main1 --tag final --systems team_final current_default
```

측정 로직은 독립 스크립트 [`scripts/eval_parsing.py`](scripts/eval_parsing.py)에 있고(두 브랜치 공통), `run_experiment.py parsing`은
config의 시스템 목록으로 그것을 호출할 뿐이다. 한 프로젝트만 재려면 `python scripts/eval_parsing.py --help`.

표본은 `experiments/table_samples.yaml`의 14개 표·60쌍이다. 처음 10개 표·47쌍(기존)에 평탄화 점검용 4개 표·13쌍(추가분)을 더했다.

### 측정값 (`main2`: 새 kordoc 4.24.29 로더 출력, 같은 샘플)

비교 대상은 팀 최종본과 현재 최종본이다. 현재 최종본의 기본(`two_stage`)과 멀티에이전트는 **같은 로더·평탄화·청킹·DB**를 쓰므로
파서 지표는 하나의 값이다. 지표 1(로더)과 2(평탄화)가 전처리 단계의 지표이고, 종단 정합률은 둘을 합친 결과를 확인하는 참고 열이다.
명령: `python scripts/run_experiment.py parsing --run-id main2 --tag final --systems team_final current_default`

| 시스템 | 표본 | 1. 표 검출률 (로더) | 2. 평탄화·정리 정합률 | (참고) 종단 정합률 |
|---|---|---|---|---|
| 팀 최종 RAG | 전체 60쌍 | 98.3% (59/60) | 22.0% (13/59) | 23.3% (14/60) |
| 팀 최종 RAG | 기존 47쌍 | 100% (47/47) | 8.5% (4/47) | 8.5% (4/47) |
| 팀 최종 RAG | 추가분 13쌍 | 92.3% (12/13) | 75.0% (9/12) | 76.9% (10/13) |
| 현 버전 (기본·멀티에이전트 공통) | 전체 60쌍 | 100% (60/60) | 100% (60/60) | 100% (60/60) |
| 현 버전 (기본·멀티에이전트 공통) | 기존 47쌍 | 100% (47/47) | 100% (47/47) | 100% (47/47) |
| 현 버전 (기본·멀티에이전트 공통) | 추가분 13쌍 | 100% (13/13) | 100% (13/13) | 100% (13/13) |

현 버전 값은 `main2` 색인에 쓴 로더 출력(`output/new_parser_md`)에 최종 평탄화 코드를 적용하고 재청킹한 것이다. 평탄화 개선 내용은
[`docs/BUGFIXES.md`](docs/BUGFIXES.md) 25번 항목에 기록했다.

`main2` 색인은 57건 모두 성공했다. HWP 2건(한림디자인고 교복, 울산과학대 그룹웨어)은 호출당 후보 30개에서 모델이 빈 응답을 내
실패해, 후보 10개로 재시도해 성공했다(`main2/current_default_build.json`의 `retry_note`).

### 읽는 법 (측정값과 구분한 해석)

- 팀의 미검출 1쌍은 **테두리 없는 표**(업종별 추정가격 비율)의 `전문공사 업종별 합계 = 85,530,000`이다. 라벨과 값이 한 줄로
  이어지지 않아 검출로 세지 않았다. 나머지 비율 표 쌍은 평문 목록에서도 `라벨 : 값` 한 줄로 남아 검출로 센다(검출 정의 참고).
- 팀의 기존 10표 정합률 8.5%는 대부분 **평탄화 단계**에서 생긴다(검출 100%, 평탄화·정리 8.5%). 첫 줄을 헤더로 잘못 잡아
  라벨이 값 자리로 밀리고 `Col3` 같은 가짜 열 이름이 붙는다. 로더(LibreOffice 경유)는 이 표들을 표로 내놓았다.
- 표본 14개 표는 평탄화 결함을 찾는 과정에서 모은 것이라 **현 버전의 100%는 일반화 증거가 아니다.** 독립 확인은 새 문서의 표로 해야 한다.
- 두 시스템의 값은 입력 경로가 다른 상태(팀: HWPX → LibreOffice → PDF → Markdown, 현 버전: HWPX → kordoc 직접)에서 각자의
  로더 출력 위에서 잰 것이다. 평탄화 코드만의 우열이 아니라 "각자 로더 + 평탄화"의 결과다.

## DB 비교: 같은 프로세스에 팀 DB와 최신 DB (사전 측정, 2026-11-01)

**목적과 위치.** "DB만 바꾸면 결과가 어떻게 달라지는가"만 본 사전 측정이다. 3개 시스템 본 실험(11월 2일 이후, 엑셀 금액 반영)과는 별개이며 그 결과와 합치지 않는다.
RAG 프로세스는 이 저장소의 현재 버전(`two_stage`)으로 고정하고 DB만 바꿨다.

| 이름 | DB | 프로세스 |
|---|---|---|
| 현재 프로세스 + 팀 DB | 팀 프로젝트 DB (청크 1,844개) | 현재 버전 |
| 현재 프로세스 + 최신 DB | `main2` DB (청크 1,207개, kordoc 4.24.29 + 최종 평탄화) | 현재 버전 |

**조건.** 문항은 `new20`(m1~m20) + `new20_v2`(n1~n20) 40개, `top_k=5`, 로컬 gpt-oss:20b(답변·Judge 동일), 40문항 모두 오류 없이 완료.
DB 차이를 가리지 않도록 두 가지를 껐다.
- CSV 단축 경로: `CSV_SHORTCIRCUIT_ENABLED=false` (엑셀에 금액이 없어 오답을 내므로).
- 기관 개요·청크 예산·기관 문서 스캔 단축 경로: 검색을 건너뛰고 캐시로 답하는 경로라 `HWP_RAG_FORCE_RETRIEVAL=1`로 우회했다
  (`scripts/run_experiment.py`의 `_execute`가 우회 판정만 고정한다. 프로세스 코드는 수정하지 않았다).

**재현.** 같은 커밋의 `git worktree` 두 개를 만들어 하나에는 팀 DB 복사본을, 다른 하나에는 최신 DB 복사본을 `data_index/chroma_B`로 넣고
`run_experiment.py`의 `systems`에서 `project_root`로 가리킨다. 저장해 둔 DB 스냅샷은 `hmr_db_snapshots/{team_final,current_default}`이며 이후 검증에도 그대로 쓴다.

```bash
python scripts/run_experiment.py --config <위 두 worktree를 systems로 둔 config> query    --run-id dbcmp3 --systems proc_on_team_db proc_on_cur_db
python scripts/run_experiment.py --config <같은 config>                              evaluate --run-id dbcmp3
```

### 측정값 (`dbcmp3`, 40문항)

답변 품질 (Judge, 1~5점)과 검색 단계 지표:

| 지표 | 팀 DB | 최신 DB |
|---|---|---|
| Correctness 전체 | 4.475 | 4.425 |
| Correctness 기존(m1~m20) / 일반화(n1~n20) | 4.55 / 4.40 | 4.60 / 4.25 |
| Faithfulness | 4.800 | 4.725 |
| Answer coverage | 4.225 | 4.150 |
| Context relevance | 4.750 | 4.775 |
| 회귀 문항 통과율 (m2, m17, m19, m20) | 100% (4/4) | 75% (3/4) |
| 수치 비교 정확도 (3문항) | 66.7% | 66.7% |
| 표 정합률 (60쌍, 최종 청크) | 23.3% | 100% |
| context hit@3 / hit@5 | 0.850 / 0.925 | 0.875 / 0.900 |
| 정답 값 MRR / 출처 MRR | 0.755 / 0.918 | 0.798 / 0.938 |
| 헤더 포함률 | 0.687 | 0.784 |
| 평균 소요 시간 (문항당) | 70.4초 | 67.7초 |

문항별 짝 비교 (Wilcoxon 부호 순위 검정, 40문항): Correctness 차이 −0.05 (p=0.82), Faithfulness −0.075 (p=0.50),
Answer coverage −0.075 (p=0.81), Context relevance +0.025 (p=1.00). Correctness가 다른 문항은 11개(최신이 높은 문항 5, 낮은 문항 6, 같은 문항 29).

검색 지표 (ranx, 프로세스를 거친 최종 상위 5개):

| 단위 | 지표 | 팀 DB | 최신 DB |
|---|---|---|---|
| 문서 | hit@1 / hit@5 | 0.950 / 0.975 | 0.975 / 0.975 |
| 문서 | nDCG@5 | 0.963 | 0.975 |
| 청크 | hit@1 / hit@5 | 0.750 / 0.950 | 0.850 / 0.950 |
| 청크 | recall@5 | 0.910 | 0.945 |
| 청크 | nDCG@5 / MRR@5 | 0.814 / 0.823 | 0.898 / 0.885 |

청크 정답은 청크 ID가 DB마다 달라 평가셋의 `chunk_uids`를 쓰지 못하고, 정답 문장의 핵심 수치·날짜를 담은 청크를 DB별로 찾아 만들었다
(`scripts/build_qrels.py`, 결과 `eval_resources/retrieval/qrels_*.json`). 문서 정답은 평가셋의 `ground_truth.sources`로 DB와 무관하다.

**두 DB가 다르게 답한 문항 (Correctness, 팀 → 최신):**
m11 0→5, n16 1→5, n6 3→5, m13 4→5, m5 4→5 / m17 5→0, n13 5→0, n17 4→2, m14 5→4, n10 5→4, n19 5→4.

**hit@5(청크)에서 빠진 문항:** 팀 DB는 m11(문서는 맞고 정답 청크를 못 가져옴)과 n4(정답 문서를 못 찾음), 최신 DB는 n4와 n13(문서는 맞고 정답 청크를 못 가져옴).
n4는 두 DB 모두 정답 문서(신목중학교)가 아닌 같은 형식의 다른 학교 교복 공고(서야고 등)를 가져왔고, `main1`(옛 DB)에서도 같았다.

### 프로세스 없이 검색기만 측정한 값 (`scripts/eval_retriever.py`)

위 측정과 별도로 프로세스를 거치지 않고 `VectorStore.search`(앱과 같은 `mode=dynamic`, `hybrid_alpha=0.6`)만 호출해 상위 결과를 ranx로 평가했다.
후보 풀(재정렬 대상 수)은 팀 코드 기본값(`top_k=5` 기준 40)에 맞췄고, 현재 코드의 기본값(150)은 참고 행으로 둔다. 40문항, 정답 라벨은 위와 같다.

| 단위 | 시스템 | hit@1 | hit@5 | recall@5 | nDCG@5 | MRR@10 |
|---|---|---|---|---|---|---|
| 청크 | 팀 DB | 0.475 | 0.850 | 0.707 | 0.572 | 0.619 |
| 청크 | 최신 DB (풀 40) | 0.650 | 0.725 | 0.698 | 0.665 | 0.683 |
| 청크 | 최신 DB (풀 150, 참고) | 0.700 | 0.775 | 0.748 | 0.715 | 0.733 |
| 문서 | 팀 DB | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 문서 | 최신 DB (풀 40) | 0.825 | 0.875 | 0.875 | 0.848 | 0.844 |
| 문서 | 최신 DB (풀 150, 참고) | 0.875 | 0.950 | 0.950 | 0.908 | 0.895 |

섹션 확장("개선" 버전: 검색된 청크를 같은 섹션 전체로 확장, 합쳐진 섹션은 순위 한 칸, 섹션 글자 수가 예산 1,000자 이하일 때만)은 이 설정에서 모든 지표가
최신 DB와 같았다. 청크가 이미 최대 1,000자라 예산 안에 드는 다중 청크 섹션이 레벨 2에서 4개뿐이기 때문이다(레벨 1은 78개, 1,500자 이하 109개, 2,000자 이하 132개).
설정(레벨, 예산)은 아직 탐색하지 않았다.

### 읽는 법 (측정값과 구분한 해석)

- 답변 품질은 두 DB가 통계적으로 구분되지 않는다(Correctness p=0.82). 40문항에서 문항별 차이는 서로 상쇄됐고 한쪽이 앞선다고 말할 근거는 없다.
- 프로세스를 거치면 문서 단위 검색은 두 DB가 거의 같아진다(hit@5 0.975). 검색기만 볼 때 최신 DB가 문서를 놓치던 것(0.875)은 프로세스의 기관명 처리와 더 큰 후보 풀(요청 24개 이상 → 풀 360 이상) 뒤에 사라졌다.
  이는 프로세스를 거친 값과 검색기 단독 값이 다른 이유로 추정한 것이며, 어느 요소가 얼마나 기여했는지는 분리해 측정하지 않았다.
- 청크 단위에서는 최신 DB가 1위 적중과 nDCG에서 앞선다(0.85 대 0.75, 0.898 대 0.814). 다만 청크 정답 라벨을 DB마다 따로 만들었고 팀 DB는 청크가 더 많아(1,844 대 1,207)
  같은 후보 풀(360)이 전체의 20%와 30%에 해당하는 차이가 있다. 이 차이는 DB의 특성이므로 설정을 따로 맞추지 않았다.
- 표 정합률 23.3% 대 100%는 위 "표 지표" 절과 같은 결과를 최종 청크에서 다시 본 것이다.
- 회귀 문항 m17(공사기간)은 최신 DB에서 0점이다. 정답 청크는 상위 5개의 1위와 2위로 가져왔지만(같은 청크가 두 번 나옴) 답변이 "문서에서 확인되지 않습니다"였다.
  `main1`(옛 DB)에서도 같은 답이었다. 원인은 아래 "원인 진단"에서 추적했다(컨텍스트 발췌 단계에서 정답 줄이 잘림).

### 한계

- 이 측정은 **단축 경로를 모두 우회한 조건**이다. 실제 앱에서는 일부 질문이 단축 경로로 답하므로 위 값이 앱의 성능을 그대로 나타내지는 않는다.
  우회가 hit@5에서 빠진 문항에 영향을 주었는지는 아래 "원인 진단"에서 검증했고, 영향이 없었다.
- 40문항, 1회 실행이라 한 문항의 차이가 점수에 크게 반영된다. 비결정성(`temperature=0`에서도 달라짐)은 따로 보지 않았다.
- 정답 청크 라벨은 정답 문장의 수치·날짜가 든 청크를 자동으로 찾은 것이라, 수치가 없는 정답이나 같은 수치가 여러 청크에 있는 경우는 부정확할 수 있다. 일부만 수작업으로 확인했다.
- 같은 기관·같은 형식의 공고가 여럿인 경우(n4)는 두 DB 모두 풀지 못했다. 원인은 아래 "원인 진단"에 있다.

### 원인 진단 (2026-11-01, `scripts/diagnose_answer.py`, 결과 `eval_resources/diagnosis/run1/`)

정답이 갈리거나 틀린 9문항(m11 m13 m17 n4 n5 n6 n13 n16 n17)을 두 DB에서 다시 돌리며 생성 단계의 입력(컨텍스트)과 모델의 추론(`reasoning`)을 기록했다.
호출은 문항당 4번(시각 자료 판정, 근거 압축, 답변 생성, 편집)이고, 프롬프트는 바꾸지 않았다.

**1. 단축 경로 우회는 원인이 아니다.** 단축 경로를 켠 조건과 검색을 강제한 조건에서 9문항 × 2 DB의 검색 결과가 같았고,
켠 조건 18건 중 단축 경로가 작동한 경우는 없었다(생성 시간이 0인 건 없음). 결과가 달라진 문항은 n17, n6뿐이며 둘 다 정답이 컨텍스트에 있는 상태에서
모델 응답이 달라진 것이다(LLM 비결정성).

**2. 검색 단계에서 정답 값이 상위 5개에 없던 경우.**

| 문항 | DB | 원인 |
|---|---|---|
| n4 | 둘 다 | 질문의 기관(신목중학교)을 추출하지 못함. 모델 추론은 "문서는 서야고등학교 것이라 확인되지 않는다"였고 주어진 입력에서는 맞는 행동이다 |
| m11 | 팀 | 문서(전주사랑의집)는 맞게 가져왔으나 `기초금액`이 든 청크가 아니었다 |
| n13 | 최신 | 문서는 맞으나 `공사기간`이 든 청크를 가져오지 못함 |

기관 추출 결함: `_extract_org_names_from_query`의 토큰 겹침 규칙(4단계)은 겹치는 단어가 2개 이상이어야 후보로 인정한다.
n4, m11은 질문이 기관을 고유명 하나(신목중학교, 전주사랑의집)로만 가리키므로 겹침이 1개라 후보에서 빠진다.
후속 폴백(5단계, 프로젝트 힌트)은 `_extract_project_hints_from_query`가 힌트를 돌려줘야 동작하는데 n4는 `['동복 및 하복']`, m11은 `[]`이라 사실상 실행되지 않는다.
현재 코드로 40문항을 돌렸을 때 첫 후보가 정답 기관인 문항은 38개이고, 후보가 없는 문항은 m11과 n4, 오답 기관만 나온 문항은 0개다(두 DB의 기관 목록이 같다).

**3. m17(최신 DB): 정답 청크를 1위로 가져왔는데 생성 입력에 정답 줄이 없었다.**
컨텍스트 구성 시 청크가 700자(`CONTEXT_MAX_CHARS`)를 넘으면 `_extract_relevant_excerpt`가 질문 키워드가 든 줄만 점수순으로 남긴다. 그런데 질문 키워드를 어미·조사가 붙은 채로 비교한다
(`공사기간은`, `대집행복구공사의`, `며칠인가요`). 그래서 `공사기간: 착공일로부터 60일` 줄은 숫자 점수 1점만 받았고, 점수 2점인 428자짜리 일반 문단이 예산을 먼저 채워
정답 줄이 잘렸다. 이어진 근거 압축 단계가 "관련 근거 없음"을 냈다. 700자를 넘는 청크는 최신 DB 18.2%(220/1,207), 팀 DB 11.4%(210/1,844)라 이 잘림에 최신 DB가 더 취약하다.
`CONTEXT_MAX_CHARS`와 `CONTEXT_TOP_RESULTS`(6)는 환경변수로 바꿀 수 있다.

**4. 나머지 "모델 실패"는 대부분 부분 답변이다.** n6, n16("총 7기"), n17("총 3기")은 요약만 답한 경우이고 검색 문제가 아니다.
이 진단의 `answer_ok`는 정답 핵심 값의 절반 이상이 답에 있어야 통과시키는 거친 휴리스틱이라, m11(최신)이 주된 값 `50,000,000원`을 맞혔는데도 실패로 센 것 같은 거짓 음성이 있다.
답변 품질 판단은 위의 Judge 점수가 기준이고, 이 진단은 원인 분류용이다. 9문항 표본이므로 비율로 일반화하지 않는다.

### 청크 정확도: 누락 (`scripts/eval_omission.py`)

DB 구축 단계의 누락을 로더 출력의 연속 8글자 조각이 최종 청크에 남은 비율(coverage)로 쟀다(42개 HWP/HWPX 문서, 두 시스템의 로더 출력이 모두 있는 것).

| 지표 | 최신 | 팀 |
|---|---|---|
| 자기 로더 출력 → 자기 청크 coverage 평균 | 0.978 | 0.938 |
| 상대 로더 출력 → 이쪽 청크 (교차) | 약 0.88~0.90 (양방향 비슷) | |

- 최신 DB에서 누락이라 할 만한 근거는 찾지 못했다. 팀 DB 쪽 낮은 값의 원인(누락인지 로더 차이인지)은 분리하지 못했다.
- 한계: 표를 `라벨: 값`으로 평탄화하면 표 안쪽 조각이 깨져 표가 많은 문서의 coverage가 낮게 나온다(하한값). 청주하이텍고 교복 문서의 "빠진 문구"는 확인해 보니 모두 최신 청크에 있었다.
  PDF 원본 문서는 현재 로더 출력이 없어 제외했다. 누락과 중복(한쪽 청크가 겹쳐 늘어난 부분)은 글자 수 비로 분리하지 못했다.

### 섹션 확장 탐색 (`scripts/sweep_section_expansion.py`)

검색된 청크를 같은 섹션 전체로 확장하고 합친 섹션이 순위 한 칸을 쓰는 설정을 레벨(`section_uid`, `section_level1`) × 예산(1,000~무제한)으로 훑었다(최신 DB, 풀 40).
- `section_uid`: 어느 예산에서도 효과 없음. 섹션 평균이 1.2청크라 확장할 내용이 거의 없다.
- `section_level1`: 예산 1,000자에서 1문항 개선(청크 hit@5 0.725→0.75), 예산 무제한에서 2문항 개선되지만 컨텍스트 글자 수가 84% 늘어난다.
- 결론: 현재 계층 구조에서는 얻을 것이 작다. 보류.

### 페이지 정보

앱은 컨텍스트 머리글과 출처에 `p.N`을 그대로 보여 주고 걸러내지 않는다. 그런데 최신 DB는 57개 문서 중 43개(HWP/HWPX 전부)가 `page_start=1`이다.
kordoc 4.24.29의 JSON에는 블록별 `pageNumber`와 `pages`가 있고 청커는 `<<PAGE: N>>` 마커를 이미 해석하지만, 파서 skill이 마커를 내보내지 않는다.
한글(HWP) 실제 쪽 번호와 맞는지는 검증하지 않았으므로 적용은 미룬다.

## 실행 기록과 겪은 문제 (재현 시 참고)

실험을 처음 돌릴 때 실제로 막혔던 지점과 해결을 순서대로 남긴다. 같은 환경에서는 위 "직접 실행하기"만 따르면
되고, 아래는 왜 그렇게 설정했는지의 근거다.

| 단계 | 상황 | 원인 | 조치 |
|---|---|---|---|
| prepare | 팀 전처리기는 `.hwpx`를 처리하지 않음 | `preprocessor.py`가 `.hwp`만 PDF로 변환 | 팀 코드는 그대로 두고 hwpx 18건을 LibreOffice로 먼저 PDF 변환(`prepare`가 자동 수행) |
| build(팀) | 57/57 성공, 약 898초 | — | 문서별 시간은 `<run-id>/team_final_build.json` |
| build(현재) | HWP/HWPX 42건 전부 실패 | ① 이 저장소의 변환 호출이 예전 `hwp2md` 명령에 의존(이 명령은 skill이 아니라 별도 서비스 패키지의 콘솔 스크립트이고, 이 머신에서는 그 editable 설치 경로가 사라져 있었음) ② 실행기가 실패를 "색인 완료"로 보고 | 변환을 **파서 skill의 `run_pipeline.py` 직접 호출**로 교체(`scripts/parser_bridge.py`, 위치는 `HWP_SKILL_DIR`). 실행기는 성공 건수가 코퍼스 문서 수와 다르면 오류로 중단하도록 수정 |
| build(현재) | skill을 gpt-oss:20b로 돌리면 `JSONDecodeError: Expecting value: line 1 column 1` | skill 기본 백엔드(`--backend ollama`)는 Ollama 네이티브 `/api/chat`에 `think:false`+`format:json`을 보내는데 gpt-oss는 이를 따르지 않고 빈 응답을 돌려줌 | skill 문서(SKILL.md)의 OpenAI 호환 백엔드 사용: `--backend openai --base-url http://localhost:11434/v1 --api-key ollama-local` |
| build(현재) | 위 백엔드로도 같은 오류 | Ollama `/v1` 기본 컨텍스트 4096토큰 — 실측: `prompt_tokens 4050 + completion_tokens 46 = 4096`, `finish_reason: length`, 본문은 비고 추론(reasoning)만 채워짐 | `OLLAMA_CONTEXT_LENGTH=32768`으로 Ollama 서버를 재기동 |
| build(현재) | HWP/HWPX 42건 중 5건 실패(`HTTP 500`, 정확히 5분 경과) | skill이 LLM 호출에 300초 제한을 두는데, 후보가 많은 문서는 한 번의 Pass1b 호출이 8GB GPU에서 그보다 오래 걸림(기본 호출당 후보 70개) | skill 문서의 `--max-candidates-per-call`을 30으로 낮춰 전체를 다시 구축(`llm.parser_max_candidates_per_call`). 그래도 실패한 5건은 10으로 낮춰 재처리. 문서별 값은 `current_default_build.json`의 `parser_batch` 필드 |

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

> **후속 계획 (미실시):** 엑셀에 사업 금액·요약이 없어 팀 CSV 단축 경로가 금액류 질문에 오답을 낸다. 이를 해소하려면 팀 프로젝트처럼 입찰공고목록에 해당 정보를 보강해야 한다. 나라장터가 11월 2일 재개되면 해당 날짜(2026-08-08 ~ 08-09) 공고의 금액·요약을 엑셀에 추가한다. 엑셀은 질의 시점에만 읽히고 DB 구축에는 쓰이지 않으므로 **팀 DB는 그대로 재사용**하고, 현 버전 DB는 새 kordoc(4.24.29)과 최종 평탄화 코드로 `main2`로 이미 다시 만들었다(57/57). 이후 질의·채점을 새 `run-id`로 다시 돌린다. 이 `main1`의 질의·채점은 금액 컬럼이 없는 입력 기준이라 새 결과와 합치지 않고 참고로만 둔다.

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
