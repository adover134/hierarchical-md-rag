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
- **LLM은 전부 로컬 `gpt-oss:20b`**: 답변·질의의도·Judge, 그리고 현 버전 파서(Pass1b)까지. 팀 코드는
  `OPENAI_BASE_URL` 환경변수로 같은 로컬 엔드포인트를 쓴다(코드 수정 없음).
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
# 1) Ollama 서버(다른 터미널)와 모델
ollama serve
ollama pull gpt-oss:20b

# 2) 팀 프로젝트 저장소를 이 저장소와 같은 위치(../RAG_project)에 받는다
git clone https://github.com/adover134/RAG_project.git ../RAG_project

# 3) Python 환경(langc) — LibreOffice(soffice), hwp2md, node(npx kordoc)가 필요하다
conda activate langc
pip install -r requirements.txt
```

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
