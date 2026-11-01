# hierarchical-md-rag

이 저장소에서 작업할 때 항상 지키는 규칙이다.

## 모델 역할: GPT는 생성, Claude가 채점

- **GPT(로컬 `gpt-oss:20b`)는 답변 생성 전용이다.** 질의응답, 근거 압축 등 RAG 프로세스의 생성 호출에만 쓴다.
- **채점(Judge)은 항상 Claude가 한다.** `gpt-oss:20b`로 채점하지 않는다. 성능이 낮고, 자기가 만든 답변을 스스로 채점하게 되기 때문이다.
- 별도의 API 키를 쓰지 않고, **서브에이전트를 호출해서 채점한다.** 저장된 답변을 시스템·실행 식별 없이 섞어 넘기고, 같은 루브릭(`src/evaluation/llm_judge.py`의 4개 축, 0~5점)으로 채점한다. 도구는 `scripts/claude_judge.py`.
- 보고하는 모든 점수 문서에 "심사: Claude(서브에이전트)"를 명시한다. 예전 `gpt-oss:20b` 채점값은 참고용으로 표시해서만 남긴다.
- `scripts/run_experiment.py evaluate`는 Claude 채점 캐시가 없으면 gpt-oss로 대신 채점하지 않고 멈춘다. `scripts/eval_retrieval.py`의 `--judge_model` 경로는 팀에서 가져온 것이라 보고용 점수에 쓰지 않는다.
- 최종 채점 결과도, 추가 개선 여부의 판단도 항상 Claude 채점을 기준으로 한다(2026-11-02 사용자 확정). gpt-oss 채점은 Correctness를 평균 0.1점 낮게 매기고(같은 답변 120건 중 차이 난 26건에서 19건) Context relevance는 크게 후하게 매겼다.
