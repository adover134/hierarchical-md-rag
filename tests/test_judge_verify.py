"""채점 1단계 검증(`scripts/judge_verify.py`)의 테스트."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from judge_grade import BASE_INSTRUCTION  # noqa: E402
from judge_verify import INSTRUCTION_LINE, SCHEMA, VERIFY_PROMPT, attach, target_matches, verify_question  # noqa: E402

CORPUS = {"documents": [{"no": 1, "file": "가 공사_가 기관", "lines": ["기초금액: 1원"]}], "notices": []}
RESULT = {"notices": [{"file": "가 공사_가 기관", "notice_no": "1호", "why": "이름", "quotes": ["기초금액: 1원"]}],
          "answer": "1원", "unverified": ""}


def test_the_verifier_gets_only_the_question_and_the_results_of_its_own_requests():
    seen, replies = [], [{"action": "search", "query": "기초금액"}, {"action": "final", "result": RESULT}]

    def ask(message):
        seen.append(message)
        return replies.pop(0)

    out = verify_question("기초금액은?", CORPUS, ask)
    assert out["result"] == RESULT and [s["action"] for s in out["steps"]] == ["search"]
    assert "기초금액은?" in seen[0] and "[문서 1]" not in seen[0] and "[문서 1]" in seen[1]


def test_the_excel_action_shows_the_amount_column_and_docs_lists_the_documents():
    corpus = {**CORPUS, "notices": [{"공고명": "가 공사", "사업 금액": "1"}]}
    replies = [{"action": "excel", "query": "가 공사"}, {"action": "docs"}, {"action": "final", "result": RESULT}]
    out = verify_question("질문", corpus, lambda message: replies.pop(0))
    assert "사업 금액=1" in out["steps"][0]["output"] and out["steps"][1]["output"] == "문서 1: 가 공사_가 기관"


def test_the_verifier_is_told_to_read_the_notice_list_first_and_has_that_action():
    assert "공고 목록(엑셀)을 먼저 보고" in VERIFY_PROMPT and '{"action": "excel"' in VERIFY_PROMPT
    assert SCHEMA["properties"]["action"]["enum"] == ["excel", "docs", "search", "show", "final"]


def test_the_grader_is_told_to_check_the_notice_and_to_accept_confirmed_equivalents():
    assert INSTRUCTION_LINE.split("\n") == [
        '항목의 "검증 결과"는 원본에서 따로 확인한 것이다. 채점하기 전에 context의 문서가 검증 결과의 공고와 같은지 대조한다.',
        "생성 답이나 context가 기대 답변과 다르게 표현돼도, 검증 결과의 값이나 원문 구절로 같은 내용임이 확인되면 맞은 것으로 본다."]


def test_the_last_turn_asks_for_the_final_result_and_gives_up_without_one():
    seen = []

    def ask(message):
        seen.append(message)
        return {"action": "search", "query": "기초금액"}

    out = verify_question("질문", CORPUS, ask, max_steps=3)
    assert len(seen) == 3 and "마지막 차례" in seen[-1]
    assert out["result"] == {"notices": [], "answer": "확인 불가", "unverified": "정해진 횟수 안에 결과를 내지 못했다"}


def test_attach_adds_the_verification_to_each_item_and_one_line_to_the_instruction(tmp_path):
    (tmp_path / "batches").mkdir()
    item = {"item_id": "p1", "question": "질문", "context": "근거"}
    (tmp_path / "batches" / "batch_01.json").write_text(json.dumps([item]), encoding="utf-8")
    (tmp_path / "mapping.json").write_text(json.dumps({"p1": {"dataset": "new20", "id": "m1"}}), encoding="utf-8")
    (tmp_path / "instruction.txt").write_text("지시문\n위 파일 외에는 열지 않는다.\n", encoding="utf-8")
    attach(tmp_path, {"new20/m1": {"result": RESULT, "steps": []}})
    [got] = json.loads((tmp_path / "batches" / "batch_01.json").read_text(encoding="utf-8"))
    assert got == {**item, "검증 결과": RESULT}
    assert (tmp_path / "instruction.txt").read_text(encoding="utf-8") == "지시문\n위 파일 외에는 열지 않는다.\n" + INSTRUCTION_LINE + "\n"


def test_attach_writes_the_base_instruction_when_the_round_has_none(tmp_path):
    (tmp_path / "batches").mkdir()
    (tmp_path / "mapping.json").write_text("{}", encoding="utf-8")
    attach(tmp_path, {})
    assert (tmp_path / "instruction.txt").read_text(encoding="utf-8") == BASE_INSTRUCTION + "\n" + INSTRUCTION_LINE + "\n"


def test_target_matches_compares_the_verified_files_with_the_expected_sources():
    assert target_matches(RESULT, ["가 공사_가 기관.hwp"])
    assert not target_matches(RESULT, ["가 공사_가 기관", "나 공사_나 기관"])
    assert not target_matches({"notices": []}, ["가 공사_가 기관"])
