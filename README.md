# hierarchical-md-rag

markdown 헤더 계층(`#`/`##`/`###`)을 살려서 청킹하는 것과, 헤더를 무시하고 고정 크기로 자르는 것이
RAG 검색 품질에 실제로 얼마나 차이를 만드는지 재는 도구다. 이 저장소는 **문서를 markdown으로
변환하지 않는다** — 이미 헤더가 달린 markdown을 입력으로 받는다.

## 이 도구가 하는 일

1. 폴더 안의 `.md` 파일들을 두 가지 방식으로 각각 청킹한다
   - **hierarchical**: 헤더 경계로 먼저 나누고, 각 청크에 조상 헤더 전체("1. 입찰에 부치는 사항
     > 가. 공고명")를 `section_path`로 붙인다
   - **flat**: 헤더를 무시하고 문서 전체를 고정 크기+오버랩으로 자른다 (구조 정보 없는 markdown을
     흉내내는 베이스라인)
2. 각각 임베딩(`intfloat/multilingual-e5-small`)해서 in-memory 코사인 유사도 검색 인덱스를 만든다
3. 같은 질의셋으로 두 인덱스를 검색해서 Recall@K / MRR / Hit Position을 비교한다 — 전체 평균뿐
   아니라 질의 유형별(`fact_lookup`/`single_doc`/`multi_doc`)로도 나눠서 보여준다. 질의를 하나로
   뭉쳐 평균만 보면 어떤 유형에서 왜 차이가 나는지 진단이 안 되기 때문이다.

## 설치

```bash
pip install -e .
```

## 사용법

```bash
mdrag-eval <markdown_폴더> <질의셋.yaml> --top-k 5
```

- `<markdown_폴더>`: 헤더(`#`/`##`/`###`)가 이미 달린 `.md` 파일들이 있는 폴더. 이 도구는 그
  markdown을 만들지 않는다 — 한글 공문서라면
  [`hwp-hierarchical-md-skill`](https://github.com/adover134/korean_official_document_parser_skill)로
  먼저 변환해서 그 출력 폴더를 그대로 넣으면 된다.
- `<질의셋.yaml>`: `examples/queries.example.yaml` 형식 참고. 정답 판정은 "정답 chunk_id"가
  아니라 "기대하는 문자열이 상위 K개 청크 중 어디든 있는가"로 한다 — 청킹 전략이 바뀌면 청크
  경계 자체가 달라지므로 chunk_id로는 두 전략을 공정하게 비교할 수 없기 때문이다. 질의마다
  `query_type`(`fact_lookup`/`single_doc`/`multi_doc`)을 붙이면 유형별로도 나눠서 결과를
  보여준다 — 세 유형을 고루 섞어서 작성할 것을 권장한다(예시 파일 참고).

## 검증 (로컬, 비공개 문서로 실행 — 데이터는 리포에 없음)

한국 공공기관 입찰공고문 2건(하나는 텍스트박스·첨부 서식이 섞인 복잡한 구조)을
[`hwp-hierarchical-md-skill`](https://github.com/adover134/korean_official_document_parser_skill)로
변환한 뒤, `fact_lookup`/`single_doc`/`multi_doc`을 섞은 질의 8개로 top_k=3 비교:

| 전략 | 청크 수 | 전체 Recall@3 | 전체 MRR |
|---|---:|---:|---:|
| hierarchical | 109 | **100.0%** | **0.938** |
| flat | 41 | 50.0% | 0.500 |

유형별로 나눠보면 차이가 어디서 나는지 뚜렷하다:

| 유형 (n) | hierarchical Recall@3 | flat Recall@3 |
|---|---:|---:|
| fact_lookup (2) | 100% | 100% |
| single_doc (5) | **100%** | **20%** |
| multi_doc (1) | 100% | 100% |

`fact_lookup`(예: "입찰보증금은 얼마인가요")과 `multi_doc`은 표본이 각각 2개·1개라 결론 내리기엔
너무 작지만, 이 표본에서는 두 전략이 동률이었다 — 찾는 값이 문서 어디에 있든 우연히 청크 경계
안에 잘 들어간 것으로 보인다. 반면 `single_doc`(문서 안 여러 문장을 종합해야 하는 질의, "제출
서류가 뭐가 있나요" 류)에서는 격차가 극명했다: flat이 놓친 4개 질의 전부 `single_doc`이었다 —
"입찰의 무효", "제출서류", "가격입찰서 제출", "제안설명회"처럼 문서 안에서 비교적 짧은 섹션에
담긴 내용인데, 고정 크기(1000자) 청크 안에 앞뒤 무관한 내용과 함께 섞여 들어가면서 검색 신호가
희석된 것으로 보인다. hierarchical은 섹션 경계를 그대로 청크 경계로 쓰기 때문에 짧은 섹션도
독립된 청크로 남는다 — 대신 청크 수가 더 많아진다(109 vs 41). 이건 "hierarchical이 무조건 더
촘촘히 나눈다"는 뜻이 아니라, 원본 문서의 실제 섹션 길이 분포를 그대로 반영한 결과다.

2건·질의 8개짜리 소규모 테스트라 일반화된 결론으로 보기엔 이르다 — 특히 유형별 표본이 1~2개인
`fact_lookup`/`multi_doc`은 방향성조차 신뢰하기 어렵다. `single_doc` 격차만 방향성 확인 수준으로
참고할 것.

## 한계

- 임베딩 모델 1종(`multilingual-e5-small`)만 검증했다. 모델을 바꾸면 결과가 달라질 수 있다.
- `expected_contains` 부분 문자열 매칭은 "청크에 정답 키워드가 있는가"만 보지, 실제 LLM 답변
  품질(정확도·환각 여부)까지는 재지 않는다.
