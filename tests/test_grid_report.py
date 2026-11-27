"""3x2 비교 보고서(`scripts/grid_report.py`)의 쌍체 비교 계산 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from grid_report import cell_name, paired_summary  # noqa: E402


def test_paired_summary_counts_and_mean():
    r = paired_summary([3, 4, 5, 5], [4, 4, 3, 5])
    assert (r["up"], r["down"], r["same"]) == (1, 1, 2)
    assert abs(r["mean_diff"] - (-0.25)) < 1e-9
    assert r["p"] == 1.0


def test_paired_summary_sign_test_is_two_sided():
    r = paired_summary([0] * 8, [1] * 8)
    assert r["up"] == 8 and abs(r["p"] - 2 / 256) < 1e-9


def test_paired_summary_all_equal_has_p_one():
    assert paired_summary([2, 2], [2, 2])["p"] == 1.0


def test_cell_name():
    assert cell_name("proc", "cur_db") == "proc_on_cur_db"


def test_summary_table_averages_every_answer(monkeypatch):
    import grid_report as gr

    cell = {("new20", "m1"): {"correctness": 5, "answer_coverage": 5, "faithfulness": 4, "context_relevance": 5},
            ("new20", "m2"): {"correctness": 0, "answer_coverage": 0, "faithfulness": 0, "context_relevance": 3}}
    scores = {gr.cell_name(p, d): cell for p, _ in gr.PROCESSES for d, _ in gr.DBS}
    table = gr.summary_table(scores)
    assert "| 2.000 |" in table and "거부" not in table


def test_load_scores_keeps_the_faithfulness_of_refusal_answers(tmp_path, monkeypatch):
    import json

    import grid_report as gr

    cache = tmp_path / "r" / "judge_cache" / "s"
    cache.mkdir(parents=True)
    (cache / "new20__m1__1.json").write_text(json.dumps({ax: {"score": 1} for ax in gr.AXES}), encoding="utf-8")
    (tmp_path / "r" / "s_raw.json").write_text(json.dumps([{"dataset": "new20", "id": "m1", "answer": "문서에서 확인되지 않습니다."}]), encoding="utf-8")
    monkeypatch.setattr(gr, "RUNS_DIR", tmp_path)
    assert gr.load_scores("r", "s")[("new20", "m1")]["faithfulness"] == 1
