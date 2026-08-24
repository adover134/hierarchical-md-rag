# RAG 파이프라인 버그 수정 기록

원본 팀 프로젝트를 포크하고 파서를 교체한 뒤, 57개 문서(HWP/HWPX 42 + PDF 15)로
새로 구축한 DB에 대해 eval을 돌렸을 때 답변 품질이 크게 떨어지는 문제(LLM Judge
점수 ~0.1/5)를 진단하다가 발견·수정한 것들. 파서 교체와는 무관한, 팀 원본
`src/graph/workflow.py`에 이미 있던 로직 결함들이다.

## 수정 완료 (커밋 `a8c422f`, `87c8537`)

### 1. `comparison_like`(검색 다양성 로직) 오판
- **증상**: 단일 문서 사실 질의인데도 검색 결과 순위가 스코어를 무시하고 뒤바뀜.
- **원인**: `_build_retrieval_strategy()`가 `_is_comparison_query(query)`(텍스트 기반,
  정확히 False였음)와 `len(resolved_targets) >= 2`(org_registry lexical 매칭 개수)를
  `or`로 묶어서, org 후보가 우연히 2개 이상 잡히기만 해도 비교 모드로 오판했다.
  잡힌 org 개수만으로 트리거되던 게 문제.
- **수정**: 두 조건을 `and`로 변경 — 텍스트 신호와 org 개수 신호가 동시에 있어야
  비교 모드로 판정.

### 2. `comparison_like_query`(답변 생성 로직) 동일 패턴 오판
- 위와 같은 원인이 `_answer_with_results()`에도 독립적으로 존재
  (`len(direct_explicit_orgs) >= 2`를 단독 트리거로 사용). 같은 방식(AND 조건)으로 수정.

### 3. `_extract_org_names_from_query()` 후보 우선순위 — 길이 기반 → 임베딩 기반
- **증상**: 질문과 무관한 문서가 org_name으로 잘못 확정되어 검색 범위 전체가
  엉뚱한 문서로 좁혀짐.
- **원인**: 후보 스코어링 대부분의 티어에 `len(org_name)`이 그대로 더해져서,
  두 후보가 같은 흔한 토큰(예: 기관명 접두어, "LED" 같은 우연한 약어)에서만
  겹칠 때 실제 관련성과 무관하게 **제목이 더 긴 쪽**이 이겼다.
- **수정**: 후보가 2개 이상일 때, DB와 동일한 인코더(`vector_store._create_embeddings`)로
  쿼리와 각 후보 org명을 임베딩해 코사인 유사도로 재정렬. 문자열 길이 대신 실제
  의미적 관련성으로 우선순위를 정하도록 변경.

### 4. `deadline_focus_markers`의 "일" 단독 마커 오탐
- **증상**: "마감기한" 관련 정답 줄이 있어도 전혀 무관한 상투 문구(입찰참가신청서
  서식 등)가 정답으로 뽑힘.
- **원인**: 마커 목록에 있던 "일" 한 글자가 "일반"/"일체" 등 거의 모든 문장에
  우연히 포함되어 `has_deadline` 판정이 사실상 무의미해졌고, 청크 텍스트가
  `<br>`로만 문장을 구분한 경우(`\n` 미분리) 그 상투 문구 전체가 하나의 거대한
  "줄"이 되어, 동점 상황에서의 길이 기준 tie-break로 정답 줄을 눌렀다.
- **수정**: "일" 단독 마커 제거. `deadline_pattern` 정규식이 이미
  `\d+\s*(?:시간|일|주|개월|년)` 형태로 숫자+단위 조합을 독립적으로 커버하고
  있어서 "N일" 개념은 그대로 유지됨 — 실사용 사이트 4곳 모두 정규식과 OR로
  묶여 있어 안전하게 확인.

### 5. `_extract_query_keywords()` 조사(은/는/이/가 등) 미분리
- **증상**: 질의 키워드와 문서 내용이 실제로는 일치하는데도 키워드 겹침 점수가 0점.
- **원인**: 정규식 토크나이저가 "납품기한은"처럼 조사가 붙은 통짜 토큰을 그대로
  추출해서, 문서의 "납품기한:"(조사 없음)과 substring 매칭이 안 됨.
- **수정**: `build_db.py`가 BM25 인덱싱에 이미 쓰고 있는 Kiwi 형태소 분석기를
  재사용해, 명사 태그(NNG/NNP/NNB)만 추출한 토큰을 기존 정규식 토큰에 추가.
  인덱싱 쪽과 질의 쪽의 토큰화 방식이 이제 일관됨.

## 1차 검증

수정 전 실패했던 재현 쿼리("경성대학교 대형홀 LED월 구축 사업의 납품기한은
언제까지인가요?")로 end-to-end 확인: 검색 1위가 정답 문서/청크로 확정되고,
추출된 값도 정확히 `2026. 8. 26`으로 나옴.

기존 `eval_dataset_57docs.yaml`(q1~q8, 수정 과정에서 계속 참조했던 문서들)과
전혀 겹치지 않는 신규 문서 5건으로 `eval_dataset_new8.yaml`(n1~n8)을 새로 작성해
일반화 여부를 재확인:

- **검색(retrieval) 단계는 8/8 전부 정답 문서를 찾음** (일부는 Hit@1, 비교 질의는
  Hit@3~6 — 넓은 후보 풀에서도 순위 안에 존재). 위 5개는 새 문서/새 org 조합에서도
  재발하지 않음.
- 다만 **답변 추출 단계에서 8건 중 5건(n2, n4, n6, n7, n8)이 여전히 깨진 값을
  반환** — 아래 "답변 추출 계층 버그"에서 이어서 수정.

## 답변 추출 계층 버그 (추가 커밋)

위 검증에서 드러난 5건 실패를 근본원인까지 추적해 수정. 쉬운 설명은
`docs/BUGFIXES_PLAIN.md` 참고.

### 6. `wants_unit_quantity`가 퍼센트 질의를 가로챔
- **증상**: "몇 퍼센트 이상인가요?" 같은 질의가 엉뚱한 값("7개")을 반환.
- **원인**: "몇" 토큰만으로 [수량 전용 처리기]가 트리거되는데, 이 처리기는 `%`를
  전혀 다루지 않고 못 찾으면 함수 전체를 `None`으로 끝내버려서, `%`를 정상
  처리하는 [숫자 전용 처리기](순서상 뒤에 있음)로 넘어갈 기회조차 없었다.
- **수정**: 트리거 조건에 "문장에 %/퍼센트가 있으면 수량 처리기로 안 보낸다"는
  조건 추가. 한 줄 변경.

### 7. 비교 답변이 "단일값 압축" 로직에 의해 손상됨
- **증상**: "A사업과 B사업 중 예산이 더 큰 건?" 같은 비교 질의가 backtick 파편이
  섞인 깨진 텍스트("사업비는 `사업비는 중심, B 문서는`입니다.")를 반환.
- **원인**: 정상적으로 만들어진 4단 비교 답변("A 문서/B 문서/공통/차이")이 후처리
  단계에서 "이건 단답형 질문이네"로 오판되어, "답변 안 첫 backtick 구간을 그냥
  뽑아서 답으로 쓴다"는 무조건적 로직에 걸림. 이런 "무조건 압축" 지점이 한 곳이
  아니라 세 곳이나 있었다.
- **수정**: 이미 있던 "이 답변이 비교문 구조인지" 판별 헬퍼(`_has_comparison_structure`,
  이미 다른 3곳에서 검증되어 쓰이는 중)를 재사용해 저 세 곳 전부에 "비교문이면
  건들지 마" 가드 추가. 새 정규식 없음.

### 8. 규칙 기반 추출 결과가 미심쩍어도 무조건 최종 답으로 확정됨
- **증상**: 예산/기간 질의에서 명백히 값 모양이 아닌 텍스트("026년" 등)가 그대로
  최종 답으로 나감 — LLM 생성 경로는 아예 호출도 안 됨.
- **원인**: 규칙 기반 추출이 뭘 내놓든(빈 문자열이 아닌 한) 그대로 신뢰하고
  바로 반환하는 구조. "결과가 이상한지" 판별하는 장치가 전혀 없었음.
- **수정**: "질의 유형에 맞는 값 모양(콤마 찍힌 금액, 숫자+기간단위, % 기호,
  라벨 중복 래핑 없음)을 갖췄는지" 검사하는 게이트(`_extraction_is_implausible`)
  신규 추가. 안 갖췄으면 규칙 기반 답을 확정하지 않고, 이미 구축돼 있던
  2단계 근거기반 LLM 생성 경로로 넘김(`extractive_draft`는 힌트로만 남고
  최종 답은 LLM이 다시 생성). 이 게이트를 최초 추출 경로뿐 아니라, "LLM 답이
  불확실해 보이면 규칙 기반으로 보완"하는 별도 폴백 지점에도 동일하게 적용 —
  안 그러면 그 폴백이 같은 나쁜 추출값을 게이트 없이 재도입함.

### 9. `_render_single_value_answer`가 라벨을 이중으로 씌움
- **증상**: 값 자체는 맞는데 "사업기간은 `사업기간은 40일`입니다." 처럼 라벨이
  중복됨.
- **원인**: 답변 후처리 파이프라인에 "단일값으로 압축" 로직이 두 번 걸리는데,
  첫 번째 호출이 이미 "사업비는 `200,000,000원`입니다."로 라벨을 붙였는데,
  두 번째 호출이 그 결과에서 backtick만 벗기고 라벨은 안 벗긴 채("사업비는
  200,000,000원") 다시 같은 렌더러에 넣어서 라벨이 또 붙음.
- **수정**: 두 번째 호출 직전에, 이미 라벨을 정확히 벗겨낼 줄 아는
  `_extract_single_value_from_fact_answer`(6-8과 같은 함수)를 한 번 더 통과시켜
  순수 값만 남긴 뒤 렌더링. 새 정규식 없음, 기존 함수 재사용.

## 2차 검증

`eval_dataset_new8.yaml`을 질문마다 새 챗봇 인스턴스로(대화이력 누적 없이)
다시 확인:

- **n1, n3, n4, n5: 완전히 정답**, 라벨 중복도 사라짐.
- **n2: 값은 정답**(₩200,000,000)이지만 "사업비는 `금액은 ...`" 형태로 약한
  잔여 중첩 — `_extract_single_value_from_fact_answer`의 금액 정규식이 "원"
  접미사 표기만 다루고 "₩" 접두 기호 표기는 못 다루는, 이번에 고친 것과는
  다른 사소한 커버리지 공백.
- 재현 쿼리("경성대학교 대형홀...")도 재확인: `기한은 \`2026.8.26\`입니다.` —
  깨끗하게 유지됨.

## retrieval depth + 최종 검증 (추가 커밋)

n8("...몇 퍼센트 이상인가요?")을 "문서는 맞는데 청크가 틀렸다" 패턴으로 진단 —
`top_k=5`로는 정답이 담긴 "5. 낙찰자결정방법" 청크가 후보에 안 들어가고, 같은
문서의 "1. 입찰에 부치는 사항" 개요 청크만 상위 5개에 포함되는 문제였다. 이미
있던 `_probe_source_local_candidates()`("먼저 문서를 찾고, 그 문서 내부를 다시
훑는" 메커니즘, 정밀사실/시각/가이드 질의에만 연결돼 있었음)를 확장해 퍼센트/비율
질의도 이 재탐색을 타도록 했다. 그 과정에서 이 메커니즘이 애초에 `single_doc_focus`
플래그에 의존하는데, 그 플래그가 **거의 항상 False**로 계산되고 있었다는 걸
발견 — 후속 항목 참고.

### 10. `single_doc_focus`가 org 후보 2개 강제 패딩 때문에 거의 항상 False
- **원인**: `resolved_targets`는 "비교 대상 org 복원"용 함수가 항상 최소 2개까지
  강제로 채워서 반환하는데(진짜 비교 질의인지와 무관하게), 이 패딩된 개수를
  그대로 `single_doc_focus` 판정에 `target_org_count >= 2 → False`로 재사용하고
  있었다. 57개 문서 코퍼스에서는 거의 모든 질문이 org 후보 2개는 우연히 찾아지므로,
  `single_doc_focus`가 사실상 항상 False가 되어 `source_local_probe`를 포함한
  여러 다운스트림 로직이 조용히 무력화되고 있었다.
- **수정**: 질의 텍스트 자체가 진짜 비교형(`_is_comparison_query`)일 때만 패딩된
  개수를 신뢰하고, 아니면 최소 1개로 취급하도록 변경.

### 11. `is_comparison_query`가 "~중 ~가 더 큰/많은 것은?" 표현을 놓침
- 10번 수정 직후 n6/n7(진짜 비교 질의)이 오히려 회귀 — 이 문구가
  `is_comparison_query`의 좁은 마커 목록("비교"/"차이"/"A 문서"/"B 문서" 등)에
  안 걸려서 `single_doc_focus=True`(틀림)로 오판된 것. 한국어 비교급 표현
  "중 ... 더 큰/많은/작은/높은/적은/긴/짧은"에 대한 정규식 추가 — org 매칭
  개수에 의존하지 않는 순수 텍스트 신호라 오늘 아침 고친 오탐 방지 로직과
  충돌하지 않음(회귀 없이 재확인).

### 12. `wants_direct_fact`/`wants_project_period`에 "기간"/"며칠" 누락
- 함수 최상단 게이트(`wants_direct_fact`) 키워드 목록에 "기간"/"며칠"이 아예
  없어서, 기간을 묻는 질의(n1, n4)가 `_extract_direct_fact_from_results`의
  첫 줄에서 바로 `None`을 반환하고 있었다. `wants_project_period`도 "사업"
  리터럴에 고정돼 있어서 "공사기간"류 표현(건설 RFP에 흔함)을 놓쳤다. 둘 다
  키워드 추가로 해결.

### 13. `_extraction_is_implausible`가 "[26년 브랜드사업]" 같은 연도 표기를 기간 값으로 오인
- 대괄호 바로 뒤 숫자를 제외하는 부정 lookbehind를 넣었었는데, 정규식 엔진이
  그 매칭에 실패하면 숫자 중간(예: "26" 중 "6")부터 다시 시도해서 우회해버리는
  걸 놓쳤다. `[`뿐 아니라 앞 문자가 숫자인 경우도 lookbehind에서 제외하도록
  보강(`(?<![\[\d])`).

## 최종 검증

이번 검증 도중 Groq 일일 토큰 한도(200,000 TPD)를 거의 다 써서 rate limit이
반복적으로 걸렸다. 로컬 Ollama로 전환했는데 처음엔 이미 받아져 있던 `qwen3.5:9b`를
썼다가 빈 응답만 반환 — 이후 qwen3.5는 VLM 계열이라 이 순수 텍스트 2단계 프롬프트에
안 맞았을 가능성이 높다는 게 확인되어, 실제 프로덕션에서 쓰는 것과 동일한
`gpt-oss:20b`를 Ollama로 새로 받아 재검증(타임아웃 20분으로 설정, `OPENAI_TIMEOUT_SEC`
환경변수로 조정 가능).

**`eval_dataset_new8.yaml` 8문항 최종 결과 (gpt-oss:20b, 로컬)**:
- n1, n2, n3, n4, n5, n8: **전부 정답**, 라벨 중복 없이 깨끗함.
- n6, n7: 답변 구조(A 문서/B 문서/공통/차이)는 온전하지만, 여전히
  `_build_comparison_answer_from_results()`의 증거 줄 선택 품질 문제가 남음 —
  아래 "남은 문제" 참고.

## 규칙 기반 추출 계층 기본 비활성화 + n6/n7 완전 해결 (추가 커밋)

`eval_dataset_new8.yaml`에 청크 단위 GT(`chunk_uids`)를 추가해 문서 recall/청크
recall/답변 정합성을 분리 측정한 뒤, "규칙 기반 추출+근거검증 vs LLM의 context
기반 생성"을 3가지 모드로 통제 비교했다:

| 모드 | Correctness | Answer Coverage | 문서 Recall@5 | 청크 Recall@5 |
|---|---|---|---|---|
| 기본(규칙 기반 추출+근거검증 둘 다 켬) | 3.12 | 2.88 | 0.50 | 0.625 |
| 추출만 끄고 근거검증은 남김 | 1.75 | 1.62 | 0.50 | 0.625 |
| 둘 다 끔(순수 LLM) | 3.62 | 3.50 | 0.50 | 0.625 |

검색 지표는 세 모드에서 완전히 동일 — 이 토글들은 답변 생성 계층에만 영향을
준다는 뜻. "추출만 끄면 오히려 나빠지는" 이유: `_restrict_answer_to_evidence()`가
근거 정합성 검사에 쓰는 `_build_evidence_spans()`/`_extract_evidence_lines()`도
**똑같이 취약한 키워드 겹침 휴리스틱**을 쓰고 있어서, 질의 단어를 그대로 반복하는
공고명/제목 줄이 실제 사실이 담긴 줄("공사기간 : 계약일로부터 40일")보다 항상
높은 점수를 받는다. 그 결과 LLM이 맞는 답을 내도 "근거 없음"으로 오판해
통째로 폐기하고 "확인되지 않습니다"로 덮어썼다. `_extract_evidence_lines()`에
금액/기간/퍼센트 값 형태 가산점을 추가해봤지만, 제목 줄들의 키워드 밀도를
안정적으로 이기지 못했다 — 결국 근거검증 자체를 우회하는 쪽이 유일하게 확실한
개선이었다.

### 14. 기본 동작을 순수 LLM 생성으로 전환
`_legacy_extraction_enabled()`(기본 `False`) 하나로 아래 4개 지점을 통일 게이트:
`_build_non_llm_answer`, `_is_single_value_query`, `_restrict_answer_to_evidence`,
`_answer_with_results`의 `_build_comparison_answer_from_results` 직접 호출부.
규칙 기반 코드 자체는 지우지 않고 그대로 둠(향후 비교/디버깅 필요시
`HWP_RAG_ENABLE_LEGACY_EXTRACTIVE=1`로 복원 가능).

### 15. 비교 질의에서 컨텍스트 창이 한쪽 기관 청크로 채워짐
- **증상**: n6/n7 — 순수 LLM 모드로 바꿔도 여전히 깨지거나 빈 답변.
- **원인**: `_build_context()`가 `results[:context_top_n]`(비교 질의는 top-8)을
  점수 순으로 그냥 자르는데, 실제로는 한쪽 기관(B) 문서의 거의 동일한 점수대
  청크 4개가 1/3/5/7위를 다 차지해서, 다른 쪽 기관(A)의 유일한 예산 청크가
  9위로 밀려 컨텍스트 창 밖으로 빠졌다. `_retrieve_results()` 자체는 top-30
  안에서 두 기관 예산을 다 찾았는데, 최종 LLM이 보는 컨텍스트에는 한쪽만
  들어간 것 — 이러면 어떤 답변 생성 방식을 쓰든 애초에 정답을 낼 수 없다.
- **수정**: 비교 질의일 때 `results[:N]` 단순 절단 대신, org(기관) 단위로
  라운드로빈해서 양쪽이 컨텍스트 예산 안에 고르게 들어가도록 변경.

## 재검토: 문서 recall / 청크 recall / 답변 정합성 재측정 (추가 커밋 `0b25fae`)

위 "최종 결과"는 correctness 점수만 보고 낸 결론이었다. recall@5와
faithfulness를 별도로 다시 재보니 실제로는 문제가 더 있었다 — 아래 3개.

### 16. `_diversify_comparison_results()`가 실제 비교 대상이 아닌 org를 고름
- **증상**: n6/n7 recall@5=0.50, `hit_position=9` — 검색 자체(dense+lexical
  rerank)는 정답을 2위에 올려놓는데, 그 다음 다양화 단계가 9위로 밀어냄.
- **원인**: `diversify_comparison_results()`(`src/retrievers/result_postprocess.py`)가
  상위 2개 org 버킷을 항목 개수 → (1차 수정 후) 버킷 내 최고 점수 기준으로
  "추측"해서 골랐는데, 두 경우 다 실제로는 무관한 세 번째 org가 우연히 같은
  기관명 접두어("선문대학교 반도체소재공학과..." vs 정답 "선문대학교
  전자공학과...")를 공유하면서 개수/점수 모두 더 높게 나와 진짜 비교 대상을
  밀어냈다. `_build_retrieval_strategy()`가 이미 계산해둔 `resolved_targets`
  (질의에서 해석된 진짜 비교 대상 org 목록)를 이 함수에 아예 넘기지 않고
  있었던 게 근본 원인 — 버킷 추측 자체가 불필요했다.
- **수정**: `diversify_comparison_results()`에 `target_orgs` 파라미터를 추가해
  `resolved_targets`를 그대로 전달, exact/substring 매칭으로 버킷을 직접
  선택(2개 미만 매칭 시에만 점수 기반 추측으로 폴백). n6 target org가 9위 →
  2위로 복귀, recall@5 0.50 → **1.00**(팀 프로젝트 자체 historical baseline과
  동일).

### 17. short-circuit 답변 경로가 `retrieved_docs`를 안 채워 recall 측정 불가
- **증상**: n3/n5 `num_retrieved: 0` — 답변 자체는 정답인데 recall@5가 0으로
  잡힘(측정 불가를 오답으로 카운트).
- **원인**: `_finalize_payload()`의 backfill 로직이 `source_type == "csv"`일
  때만 `payload["evidence"]`에서 `retrieved_docs`를 재구성했는데,
  `_try_chunk_budget_short_circuit`(청크 예산 직접 조회 경로)은 진짜 근거를
  갖고도 문서의 `doc_type` 메타데이터 공백 때문에 `source_type`이
  `"unknown"`으로 떨어져 이 조건에 안 걸렸다.
- **수정**: 조건을 `source_type` 라벨 대신 "evidence가 실제로 존재하는지"로
  일반화 — 모든 short-circuit 경로가 공통으로 이득을 봄.

### 18. LLM Judge가 좁은 `evidence`만 보고 "근거 없음"으로 오판
- **증상**: Faithfulness 평균 2.75(팀 프로젝트 historical `avg_faithfulness:
  4.45`와 큰 격차) — Correctness는 4.75로 높은데 Faithfulness만 유독 낮음.
- **원인**: `eval_retrieval.py`의 judge 호출이 `context_text`로 `evidence`
  (추출된 핵심 근거 요약, 짧음)만 넘기고 있었는데, 실제 답변 생성 LLM은 더
  넓은 `_build_context()` 결과를 봤다. `evidence` 요약이 답변의 특정 수치를
  우연히 담지 못한 경우, judge는 "context에 없는 값 = 환각"으로 오판했다 —
  실제로는 생성 시점에 그 값을 본 게 맞는데도.
- **수정**: `context_text`를 `evidence` + `retrieved_docs` 원문으로 확장. 단,
  비교 질의는 `retrieved_docs`가 최대 24개까지 있어 그대로 다 이어붙이면 judge
  프롬프트가 로컬 judge 모델(`gpt-oss:20b`/Ollama)의 토큰 한도(~4096)를 넘어
  판정 자체가 실패했다(`total_tokens=4096`으로 파싱 실패, C/AC/F/CR 전부 0).
  문자수 임의 절단 대신 `retrieved_docs[:top_k]`로 컷오프를 맞췄다 —
  `calculate_recall_at_k()`(`src/evaluation/metrics.py`) 자체가 다중 GT
  source(비교 질의)여도 top_k를 소스 수만큼 곱하지 않고 **단일 top-k 윈도우
  안에서 strict-AND**로 판정하므로, judge에게 주는 컨텍스트도 recall@5가
  실제로 채점하는 것과 정확히 같은 창으로 맞추는 게 원칙적으로 옳다. 결과:
  Faithfulness 2.75 → **5.00**(8/8), 토큰 한도 실패 없음.

### 19. 청크 예산 단축 경로가 chunk_id를 안 채워 청크 단위 recall 측정 불가
- **증상**: §17 수정 후에도 청크 단위 Recall@5는 0.75(8문항 중 6/8) — n3/n5는
  문서 단위(`source`)는 맞는데 그 문서의 몇 번째 청크인지는 GT와 매칭이 안 됨.
- **원인**: `_finalize_payload`의 backfill(§17)이 evidence item에서
  `source`/`page`/`score`/`content`는 옮기는데 `chunk_id`는 애초에 evidence
  item 자체에 없었다. `_try_chunk_budget_short_circuit`이 근거를 채워오는
  `_find_chunk_budget_for_org()`/`_ensure_chunk_budget_cache()`가
  `vector_store.collection.get(include=["metadatas", "documents"])`로 순회할
  때, 응답에 항상 같이 들어있는 실제 Chroma id(`ids`, include 목록과 무관하게
  항상 반환됨 — 예: `"f830e1042ef485a6_1"`, GT `chunk_uids`와 동일한 포맷)를
  그냥 안 잡고 버리고 있었다.
- **수정**: "recall@1로 간주" 같은 가정 대신, 이미 순회하고 있는 zip에 `ids`를
  같이 태워 캐시에 `chunk_id`로 저장 → `_try_chunk_budget_short_circuit`의
  evidence item → `_finalize_payload` backfill까지 그대로 실어 날랐다. 즉
  실제 Chroma 문서 id를 추측 없이 그대로 전달하는 것 — n3 직접 실행 결과
  `chunk_id='f830e1042ef485a6_1'`, n5는 `'5604b6a8ec491991_1'`로 GT와 정확히
  일치함을 확인.
- **참고**: 이 경로와 별개인 진짜 CSV 단축 경로(`_try_csv_short_circuit`,
  `data_list.csv` 행 기반 응답)는 건드리지 않았다 — CSV 행 자체가 source 단위
  정답 단위라 애초에 "그 안의 몇 번째 청크"라는 개념이 성립하지 않고, 실제로
  evidence 생성부 어디에도 chunk_id를 다루는 코드가 없다. `eval_dataset_new8.yaml`
  GT에도 CSV 소스에 대한 `chunk_uids`가 없어 `calculate_recall_at_k_chunk`가
  자연스럽게 `None`(미적용)을 반환한다 — 0(오답)으로도, 1(가정된 정답)으로도
  취급하지 않는 게 맞다.

## 최종 결과 (재검토 후)

`eval_dataset_new8.yaml` 8문항: Correctness 4.75, Answer Coverage 4.50,
**Faithfulness 5.00**, Context Relevance 5.00, **문서 단위 Recall@5 1.0000**,
**청크 단위 Recall@5 1.0000**(둘 다 팀 프로젝트 historical baseline과 동일 또는
그 이상), MRR 0.8750. 남은 문제 없음.

재현 방법: `python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset_new8.yaml --judge_model openai/gpt-oss-20b`
(judge 모델은 Groq 엔드포인트 기준 `openai/gpt-oss-20b`로 지정해야 함 —
기본값 `gpt-5-mini`는 Groq에 존재하지 않아 판정 자체가 실패함). Groq 한도
소진 시 로컬 Ollama로 전환: `HWP_RAG_LLM_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama-local REASONING_MODEL=gpt-oss:20b QUERY_INTENT_MODEL=gpt-oss:20b
OPENAI_TIMEOUT_SEC=1200` — 반드시 같은 모델(`gpt-oss:20b`, `ollama pull gpt-oss:20b`로
받기)을 써야 결과가 비교 가능하다.

## 제목 반복 청크 리랭킹 버그 (추가 커밋)

`eval_dataset_new20.yaml`(m1~m20) 최신 실행(`new20_v4`)에서 문항이 문서의
사업명/프로젝트명을 그대로 반복하면, 그 사업명을 담고 있을 뿐 실제 정답이
없는 서두 소개 청크가 정답 청크보다 항상 검색 순위에서 이기는 문제가 있었다
(m1, m3, m20 재현). 이전 세션에서 원인 분석까지만 하고 `docs/NEXT_SESSION_HANDOFF.md`로
인계했던 항목 — 이번 세션에서 원인을 4갈래로 분리해 각각 수정하고
`eval_dataset_new20.yaml` 20문항 전체로 검증했다.

### 20. `_score_result()`(workflow.py) 키워드 가산점 무상한
- **증상**: 질문이 사업명 전체를 반복하면(m1), 사업명을 그대로 담은 서두
  청크가 키워드 10여 개를 전부 매치해 점수가 폭발적으로 쌓임(서두 청크
  26.5점 vs 정답 청크 8.9점) — 실제 질문 내용(낙찰자 결정 기준)과 무관하게
  이김.
- **원인**: `_score_result()`의 키워드 매치 루프가 매치 개수에 상한 없이
  `+1.4`(텍스트)/`+0.8`(source)를 누적. 사업명 반복 자체가 "관련성 높음"으로
  잘못 해석됨.
- **수정**: 매치 개수를 세되 텍스트 매치 총합은 4.2점, source 매치 총합은
  1.6점으로 상한(약 3개 매치분).

### 21. `VectorStore.search()`(vectorstore.py) candidate 창이 너무 좁음
- **증상**: m3의 정답 청크(`8d112e98e864a788_2`, 추정금액 770,250,000원)가
  원시 dense 유사도 순위 115위, m9의 정답 청크는 39위 — 기존 candidate 창
  (`max(top_k*4, 40)`)으로는 리랭킹 단계까지 아예 못 올라옴.
- **원인**: 이 코퍼스(`jhgan/ko-sroberta-multitask`)의 임베딩은 관공서
  입찰공고 특유의 반복적 문체 때문에, 사업명/기관명 어휘 겹침에 강하게
  좌우된다(실측: 같은 청크에 사업명·기관명을 앞에 붙이기만 해도 질의와의
  코사인 유사도가 0.392 → 0.830으로 뜀) — 구체적 사실(금액/날짜 등)만 담고
  사업명 반복이 적은 청크는 순수 dense 유사도로 순위가 크게 밀림.
- **수정**: candidate 창을 `min(count, max(top_k*15, 150))`로 확대. 코퍼스가
  1180개 청크뿐이라 비용은 거의 늘지 않음. `_retrieve_results()`가
  `VectorStore.search()`에 요청하는 자체 `top_k`(`per_call_k`)도
  `max(8, top_k*0.8)`(단일 패스 질의에선 사실상 17)에서 `max(24, top_k*1.2)`로
  올림 — candidate 창만 넓혀도 `VectorStore.search()` 자신의 반환 개수가
  작으면 소용없었기 때문.

### 22. 비교 질의가 사업명 2개를 한 문장으로 합쳐서 검색함
- **증상**: m20("한서대학교... 용역과 글로벌소상공인... 용역 중 사업예산이
  더 큰 사업은?")의 예산 청크가 후보 창을 아무리 넓혀도(top_k=120) 안 잡힘.
  m19(장성경찰서 건축/통신 비교)도 동일 증상.
- **원인**: 두 사업명을 한 쿼리 문장에 같이 넣으면 임베딩이 두 이름 사이에서
  희석돼 어느 한쪽 사업의 구체적 수치 청크와도 강하게 안 붙는다(실측: 합친
  쿼리는 top-30에도 없던 청크가, 사업명 단독 쿼리로는 7위). `resolved_targets`
  (질의에서 해석된 비교 대상 목록)는 이미 정확히 계산되고 있었지만
  `_retrieve_results()`가 검색 자체는 항상 원본 문장 하나로만 호출했다.
- **수정**: `resolved_targets`가 2개 이상이면 타겟별로 쿼리를 분리
  (`_build_target_scoped_query()` 신설 — 다른 타겟 이름과 그에 붙은 조사를
  제거해 단독 쿼리 생성)해 각각 검색 후 병합하도록 `_retrieve_results()`
  변경. m19/m20 둘 다 정답 청크가 top-2 안으로 복귀.

### 23. `_extract_org_names_from_query()`의 2글자 영문 약어 매칭이 무관한 기관을 잡음
- **증상**: m9("...생성형 AI 콘텐츠... 전자입찰서 접수 마감일시는?")가
  `resolved_targets`에 전혀 무관한 "AI기반 그룹웨어(전자결재)시스템 구축"을
  두 번째 비교 대상으로 잡아, `_should_stop_retrieval_early()`가 "두 기관 다
  커버됐다"고 오판하고 조기 종료 — 정답 청크(39위)까지 못 내려감.
- **원인**: "영문 약어(예: KOICA) 기반 기관 복원" 로직이 길이 제한 없이
  `[a-z]{2,12}` 토큰을 org명과 겹치는지만 확인해서, "AI"처럼 실제 약어가
  아닌 흔한 2글자 단어까지 매칭됨(질의의 "AI"와 무관한 다른 프로젝트명의
  "AI"가 우연히 겹침).
- **수정**: 이 매칭 분기만 3글자 이상 토큰으로 제한(같은 함수의 다른 분기는
  이미 3글자 기준을 쓰고 있었음 — 일관성 있게 맞춤).

### 24. `_ensure_chunk_budget_cache()`의 "org당 최댓값 채택" 로직이 적격심사 등급표를 예산으로 오인
- **증상**: m3가 §20~21 수정 후 직접 검색 테스트에선 통과하는데도, 실제
  `eval_retrieval.py --top_k 5` 풀 파이프라인에서는 계속 "5,000,000,000원"
  (실제 예산의 6배 이상)이라는 오답을 냄.
- **원인**: 예산 질의는 정상 검색 파이프라인 이전에 `_try_chunk_budget_short_circuit`
  (workflow.py:3103)이 먼저 응답을 시도한다. 이 숏컷이 쓰는 캐시
  (`_ensure_chunk_budget_cache()`)는 기관(사실상 프로젝트명)별로 **그 문서의
  모든 줄 중 파싱되는 숫자가 가장 큰 줄을 무조건 예산으로 채택**하는데,
  m3 문서의 적격심사 등급표 문구("추정가격 50억원 미만 10억원 이상")가
  `budget_keywords`("추정가격")를 담고 있어 후보에 끼었고, 진짜 예산
  (770,250,000원)보다 숫자가 커서 그게 캐시에 박혔다. 이 숏컷 경로는
  §20~23에서 고친 `_retrieve_results()`를 아예 안 거치므로, 검색 쪽을 다
  고쳐도 이 경로를 타는 질의는 전혀 영향을 못 받았다.
- **수정**: `_extract_budget_candidates_from_line()`에 "미만/이상/이하/초과/
  적격심사/세부기준/별표/배점/등급" 중 하나라도 포함된 줄은 예산 후보에서
  제외하는 가드 추가.

### 디버깅 로그 부재 (병행 개선)
검증 과정에서, 재검색 없이는 "그 실행 시점에 실제로 어떤 쿼리를 DB에 던졌고
어떤 청크가 잡혔는지" 확인할 방법이 없다는 게 드러났다 — 쿼리 확장/타겟
분리가 LLM 기반 질의 분석 결과에 따라 실행마다 달라질 수 있어, 나중에 같은
질문을 재검색해도 그때와 같다는 보장이 없었다. `answer()`/`_retrieve_results()`가
호출마다 실제로 실행된 검색 쿼리·후보군 크기·최종 랭킹을
`self._retrieval_debug_log`에 기록하고 `answer()` 반환값의 `retrieval_debug`
필드로 노출하도록 추가. `scripts/eval_retrieval.py`도 매 문항마다 이걸
`retrieval_debug` + `retrieved_chunks`(top_k 청크의 chunk_id/score/본문 400자)로
결과 JSON에 함께 저장하도록 변경 — 이후 실행부터는 실패 사례를 재검색 없이
바로 진단 가능. 단 `_try_chunk_budget_short_circuit` 같은 숏컷 경로는
`_retrieve_results()`를 안 거치므로 이 로그가 비어있을 수 있고, 그 자체가
"숏컷을 탔다"는 단서가 된다(§24 발견 경로).

## 검증 (`new20_v6`, Ollama 정상 기동 상태)

`eval_dataset_new20.yaml` 20문항 전체 재실행: 문서 Recall@5 **1.00**
(`new20_v4`: 1.00, 변화 없음), 청크 Recall@5 **1.00**(`new20_v4`: 0.875),
Correctness **4.30**(`new20_v4`: 3.90), Faithfulness **4.45**(`new20_v4`: 4.25),
Context Relevance 4.75. m1/m3/m9/m11/m14/m15/m18/m19/m20 전부 정답 청크가
top-5 안에 확인됨(`scripts/repro_title_repetition_bug.py`로도 별도 재확인).

### 별개로 발견한, 이번 수정 범위 밖의 문제: LLM 생성 신뢰성

위 검증 실행에서 m2, m19가 correctness=0으로 나왔는데, 둘 다
`recall_at_k_chunk=1.0`(정답 청크가 컨텍스트에 확실히 포함)이었다.
`_build_context()`로 실제 LLM에 들어간 텍스트를 직접 재구성해보니 정답
수치("86.245%")가 컨텍스트에 명확히 두 번 들어있었는데도 최종 답변은
"제공되지 않았습니다"였다.

`RFPAnswerGenerator.generate()`(`src/graph/nodes.py:439`)는 2단계 LLM 호출
구조다: (1) `EVIDENCE_REFINEMENT_PROMPT`로 컨텍스트를 근거로 압축, (2)
`ANSWER_GENERATION_FROM_EVIDENCE_PROMPT`로 그 근거 기반 최종 답변 생성.
동일 컨텍스트로 1단계만 다시 실행해보면 어떨 때는 "86.245%"를 정확히
뽑아내고 어떨 때는 놓친다 — temperature=0.0인데도 로컬 20B 모델
(gpt-oss:20b)의 실행 간 편차로 확인됐다. 결정론적 코드 버그가 아니라
retrieval/reranking 쪽 수정으로 대응할 수 있는 종류가 아니어서, 실제로
시도했던 "퍼센트를 묻는 질문엔 퍼센트 수치가 있는 청크를 우대"하는
`_score_result()` 수정도(컨텍스트엔 이미 정답이 있었으므로 효과가 없어)
되돌렸다. 리랭크 결과에서 정답 청크가 컨텍스트에 들어갔는데도 LLM이 답을
못 내는 경우는 리트리벌/리랭킹이 아니라 생성 단계(프롬프트/모델 자체)
문제로 분류해야 한다는 게 이번 세션에서 얻은 원칙 — 이 문제 자체는 이번
세션 수정 범위 밖이라 미착수 상태로 남겨둔다.
