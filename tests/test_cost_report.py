"""Langfuse 관측을 비용 지표로 묶는 계산."""

from cost_report import gpu_peak, summarize


def _obs(name, trace, seconds, usage=None, level="DEFAULT"):
    return {"name": name, "traceId": trace, "latency": seconds, "usageDetails": usage, "level": level,
            "input": None, "output": None}


def test_summarize_groups_time_and_tokens_by_question():
    rows = [
        _obs("rag-question", "a", 10.0), _obs("llm", "a", 9.0, {"input": 100, "output": 20}),
        _obs("rag-question", "b", 30.0), _obs("llm", "b", 11.0, {"input": 400, "output": 50}),
        _obs("llm", "b", 16.0, {"input": 200, "output": 300}, level="ERROR"),
    ]

    s = summarize(rows)

    assert (s["questions"], s["llm_calls"], s["failed_calls"]) == (2, 3, 1)
    assert (s["total_seconds"], s["mean_seconds"], s["max_seconds"], s["llm_share_percent"]) == (40.0, 20.0, 30.0, 90.0)
    assert (s["single_call_mean_seconds"], s["multi_call_mean_seconds"]) == (10.0, 30.0)
    assert (s["input_tokens"], s["output_tokens"]) == (700, 370)
    assert (s["max_input_tokens"], s["max_context_tokens"], s["records_with_text"]) == (400, 500, 0)


def test_gpu_peak_reads_the_sampler_file(tmp_path):
    f = tmp_path / "gpu.csv"
    f.write_text("2026/11/26 16:00:00.000, 6900, 40\n2026/11/26 16:00:02.000, 7480, 55\n")
    assert gpu_peak(f) == 7480
    assert gpu_peak(tmp_path / "none.csv") is None
