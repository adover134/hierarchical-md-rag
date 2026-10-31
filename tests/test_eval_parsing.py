"""scripts/eval_parsing.py — 표 처리 단계별 측정(프로젝트 무관)의 통합 테스트."""

from pathlib import Path

import yaml

import eval_parsing as E

REPO_ROOT = Path(__file__).resolve().parent.parent

MD = """\
## 1. 견적

| 추정금액 | 기 초 금 액 |  |  | 관 급 자 재 |  |
| --- | --- | --- | --- | --- | --- |
| 추정금액 | 계 | 추정가격 | 부가가치세 | 도급자설치 | 관급자설치 |
| 285,125,000 | 285,125,000 | 259,204,546 | 25,920,454 | - | 285,000 |

비율 목록은 평문입니다. 지반조성공사업 : 14,045,146
"""

SAMPLES = [{
    "source": "테스트 공고_기관", "kind": "2단 헤더", "group": "base",
    "pairs": [{"label": "추정가격", "value": "259,204,546"}, {"label": "부가가치세", "value": "25,920,454"}],
}, {
    "source": "테스트 공고_기관", "kind": "평문", "group": "added",
    "pairs": [{"label": "지반조성공사업", "value": "14,045,146"}, {"label": "없는라벨", "value": "9,999"}],
}]


def _system(tmp_path, **extra):
    loader = tmp_path / "loader"
    loader.mkdir()
    (loader / "step1_테스트 공고_기관.md").write_text(MD, encoding="utf-8")
    return {"name": "t", "title": "테스트", "project_root": REPO_ROOT, "loader_md_dir": str(loader),
            "loader_md_glob": "step1_*.md", **extra}


def test_stage_split_distinguishes_undetected_from_unflattened(tmp_path):
    out = E.evaluate_system(_system(tmp_path), SAMPLES, tmp_path / "work", "t")
    base, added = out["base"], out["added"]
    # 표로 내놓은 2단 헤더 표: 검출되고 평탄화 후에도 짝이 남는다
    assert (base["detected_n"], base["flatten_ok_n"]) == (2, 2)
    # 표가 아닌 문단 줄이라도 `라벨 : 값`으로 이어져 있으면 검출이다(연결이 살아 있음)
    assert (added["pairs_n"], added["detected_n"], added["flatten_ok_n"]) == (2, 1, 1)


def test_pair_missing_from_loader_output_is_undetected(tmp_path):
    out = E.evaluate_system(_system(tmp_path), SAMPLES, tmp_path / "work", "t")
    missing = [r for r in out["records"] if r["label"] == "없는라벨"][0]
    assert not missing["detected"] and not missing["flatten_ok"]


def test_end_to_end_is_none_without_chunks(tmp_path):
    out = E.evaluate_system(_system(tmp_path), SAMPLES, tmp_path / "work", "t")
    assert out["all"]["end_to_end_rate"] is None


def test_end_to_end_from_chunk_dump(tmp_path):
    dump = tmp_path / "dump.json"
    dump.write_text('[{"text": "추정가격: 259,204,546", "source": "테스트 공고_기관"}]', encoding="utf-8")
    out = E.evaluate_system(_system(tmp_path, chunk_dump=str(dump)), SAMPLES, tmp_path / "work", "t")
    assert out["base"]["end_to_end_n"] == 1  # 추정가격만 있고 부가가치세는 없다


def test_run_parsing_writes_files_and_table(tmp_path):
    samples = tmp_path / "samples.yaml"
    samples.write_text(yaml.safe_dump(SAMPLES, allow_unicode=True), encoding="utf-8")
    text = E.run_parsing([_system(tmp_path)], samples, tmp_path / "out", "x")
    assert "표 검출률" in text and "테스트" in text
    assert (tmp_path / "out" / "parsing_x.json").exists() and (tmp_path / "out" / "parsing_x.md").exists()
