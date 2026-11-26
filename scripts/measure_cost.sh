#!/usr/bin/env bash
# 질의 비용(시간, 토큰) 측정. 측정 방법과 설정은 docs/11_비용측정.md에 있다.
# 사용법: PYTHON=<파이썬> bash scripts/measure_cost.sh <실행 이름> [시스템 ...]
set -euo pipefail
cd "$(dirname "$0")/.."

run_id="${1:?실행 이름이 필요합니다}"
shift
systems=("$@")
[ ${#systems[@]} -gt 0 ] || systems=(current_default current_multi_agent)

PY="${PYTHON:-python}"
MODEL="gpt-oss:20b-batch256"
CTX=32768                          # 컨텍스트 크기(토큰)
LIMIT="${LIMIT:-}"                 # 데이터셋별 앞 N문항만(시험 실행용)
URL="http://127.0.0.1:11434"

if curl -s -m 2 "$URL/api/version" >/dev/null; then
    echo "이미 Ollama가 떠 있습니다. 설정을 맞추려면 끄고 다시 실행하세요." >&2
    exit 1
fi

out="eval_resources/experiment_runs/$run_id"
mkdir -p "$out"
server=""
sampler=""
stop() {
    [ -z "$sampler" ] || kill "$sampler" 2>/dev/null || true
    [ -z "$server" ] || kill "$server" 2>/dev/null || true
    wait 2>/dev/null || true
    server=""
    sampler=""
}
trap stop EXIT

for system in "${systems[@]}"; do
    # 방식마다 서버를 새로 띄워, 앞 방식의 프롬프트 캐시가 다음 방식의 시간을 줄이지 않게 한다.
    OLLAMA_CONTEXT_LENGTH="$CTX" OLLAMA_NUM_PARALLEL=1 ollama serve >"$out/${system}_ollama.log" 2>&1 &
    server=$!
    curl -s -f --retry 30 --retry-delay 1 --retry-connrefused -m 5 "$URL/api/version" >/dev/null
    ollama show "$MODEL" >/dev/null 2>&1 || ollama create "$MODEL" -f experiments/Modelfile.batch256
    # 웜 스타트: 모델을 미리 올려, 첫 문항의 시간에 로드 시간이 섞이지 않게 한다.
    curl -s -f -m 600 "$URL/api/generate" \
        -d "{\"model\": \"$MODEL\", \"prompt\": \"ok\", \"stream\": false, \"options\": {\"num_predict\": 1}}" >/dev/null
    nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader,nounits -l 2 \
        >"$out/${system}_gpu.csv" &
    sampler=$!
    "$PY" scripts/run_experiment.py query --run-id "$run_id" --systems "$system" --model "$MODEL" \
        ${LIMIT:+--limit "$LIMIT"}
    curl -s -m 10 "$URL/api/ps" >"$out/${system}_ps.json"
    stop
done

"$PY" scripts/cost_report.py --run-id "$run_id" --systems "${systems[@]}" --context "$CTX"
