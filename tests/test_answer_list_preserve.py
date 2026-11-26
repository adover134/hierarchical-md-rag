"""목록에 답이 있는 초안을 후처리가 자르지 않는지 확인한다(초안은 저장된 실행의 gpt-oss 출력)."""

from types import SimpleNamespace

import pytest

from src.graph.workflow import RAGChatbotV17
from src.prompts.answer_postprocess import (
    compact_answer_sections,
    find_list_answer,
    format_answer_for_readability,
)

N16 = "설치대수는 총 7기입니다.  \n- 240kW 파워뱅크 2기  \n- 디스펜서 5기  \n- 총합 7기"
M1 = (
    "낙찰자 결정 기준은 다음과 같습니다.  \n\n- **예산의 82.495 % 이상 견적 제출**  \n"
    "- **최저가격 입찰자 순으로 적격심사**  \n- **종합평점 85점 이상** (조달청 물품구매적격심사 세부기준 적용)  \n"
    "- 동일 가격 시 **추첨**으로 결정  \n\n이 기준에 따라 적격심사를 거쳐 최종 낙찰자가 선정됩니다."
)
N4 = (
    "2027학년도 신목중학교 교복의 납품기한은 다음과 같습니다.  \n- 동복: 2027 년 2 월 22일(월)  \n"
    "- 하복: 2027 년 5 월 10일(월)  \n\n- 학교 사정에 따라 변동 가능하다는 조항이 포함되어 있습니다."
)
N7 = (
    "계약기간은 계약체결일로부터 365일입니다.  \n- 계약체결일 기준 1년(365일)  \n"
    "- 단가발주는 발주일로부터 180일 이내  \n- 계약기간은 문서에 명시된 조건에 따라 정해짐"
)


def _items(text):
    return [line for line in text.splitlines() if line.startswith("- ")]


@pytest.mark.parametrize("draft, count", [(N16, 3), (M1, 4), (N4, 3)])
def test_list_answer_keeps_every_item_and_survives_repeated_processing(draft, count):
    once = format_answer_for_readability(draft, keep_list=True)

    assert len(_items(once)) == count
    assert format_answer_for_readability(once, keep_list=True) == once
    assert compact_answer_sections(once, keep_list=True) == once


def test_sentence_after_the_list_is_not_part_of_it():
    assert "최종 낙찰자가 선정" not in format_answer_for_readability(M1, keep_list=True)


def test_indented_line_belongs_to_the_item_above_it():
    draft = "설치대수는 총 7기입니다.\n- 파워뱅크 2기\n  (급속 충전용)\n- 디스펜서 5기\n(총 7 기)"

    assert find_list_answer(draft) == (["설치대수는 총 7기입니다."], ["- 파워뱅크 2기 (급속 충전용)", "- 디스펜서 5기"])


def test_answer_in_the_first_sentence_is_still_shortened():
    assert find_list_answer(N7) is None
    out = format_answer_for_readability(N7, keep_list=True)
    assert not _items(out) and len(out.splitlines()) <= 2


def test_section_labels_are_not_treated_as_a_list_intro():
    assert find_list_answer("핵심 답변: 60일\n근거 요약:\n- 착공일 기준\n- 공고문 p.1") is None


def _run_answer(draft, polish_output, query="설치대수는 몇 기인가요?", evidence="", prompts=None, mode="generative"):
    """초안이 answer()의 마지막 처리 전체(최종 생성, 근거 검사, 말투)를 거치게 한다."""
    bot = RAGChatbotV17.__new__(RAGChatbotV17)
    bot.vector_store = SimpleNamespace(last_search_results=[])
    bot.query_parser = SimpleNamespace(
        parse=lambda q: SimpleNamespace(org_name=None, query_type="ranking", confidence=1.0))
    bot._extract_org_names_from_query = lambda *a, **k: []
    bot._handle_ranking_query = lambda intent: {
        "answer": draft, "answer_mode": mode, "evidence": [{"text": evidence or draft}]}
    bot._build_visual_attachments = lambda **k: []
    bot._is_visual_intent_query = lambda q: False
    bot._serialize_retrieved_docs = lambda results: []

    def invoke(messages):
        if prompts is not None:
            prompts.append(messages[1].content)
        if isinstance(polish_output, Exception):
            raise polish_output
        return SimpleNamespace(content=polish_output)

    bot.llm = SimpleNamespace(invoke=invoke)
    return bot.answer(query)["answer"]


SHORT = "- 단답형 질의이므로 핵심 답을 1~2문장으로 짧게 제시할 것."


def _required_block(prompt):
    """프롬프트 끝의 필수 내용 블록. 지시문에도 같은 이름이 나오므로 제목 줄로 찾는다."""
    _, header, block = prompt.partition("\n[답에 반드시 담을 내용]\n")
    assert header, "필수 내용 블록이 없다"
    return block


def test_list_items_are_given_to_the_final_generation_as_required_content():
    prompts = []

    _run_answer(N16, "설치대수는 총 7기입니다.", prompts=prompts)

    required = _required_block(prompts[0])
    assert "- 240kW 파워뱅크 2기\n- 디스펜서 5기\n- 총합 7기" in required
    assert "하나도 빼지 말고" in prompts[0] and SHORT not in prompts[0]


def test_prompt_is_unchanged_when_the_answer_is_not_in_a_list():
    prompts = []

    _run_answer(N7, "계약기간은 365일입니다.", query="계약기간은 얼마인가요?", prompts=prompts)

    assert SHORT in prompts[0] and "[답에 반드시 담을 내용]" not in prompts[0]


def test_sentence_written_by_the_model_is_the_final_answer():
    sentence = "240kW 파워뱅크는 2기, 디스펜서는 5기, 총 설치대수는 7기입니다."

    assert _run_answer(N16, sentence) == sentence


def test_model_output_is_not_replaced_by_the_draft_list():
    assert _run_answer(N16, "설치대수는 총 7기입니다.") == "설치대수는 총 7기입니다."


@pytest.mark.parametrize("polish_output", ["", RuntimeError("llm down")])
def test_draft_list_is_used_when_the_final_generation_fails(polish_output):
    final = _run_answer(N16, polish_output)

    assert "240kW 파워뱅크 2기" in final and "디스펜서 5기" in final


def test_draft_list_survives_failure_when_first_item_resembles_the_first_sentence():
    # "총 7 기"처럼 띄어 쓰면 첫 줄과 첫 항목이 "기입니다"를 공유해, answer()가 둘째 줄부터 버릴 수 있다.
    draft = "설치대수는 총 7 기입니다.\n- 240kW 파워뱅크 2 기\n- 디스펜서 5 기"

    final = _run_answer(draft, RuntimeError("llm down"))

    assert "파워뱅크 2 기" in final and "디스펜서 5 기" in final


def test_only_items_with_numbers_are_required():
    prompts = []

    _run_answer(N4, "납품기한은 문서와 같습니다.", query="납품기한은 언제인가요?", prompts=prompts)

    required = _required_block(prompts[0])
    assert "동복" in required and "하복" in required and "변동" not in required


def test_every_item_is_required_when_no_item_has_a_number():
    draft = "제출 서류는 다음과 같습니다.\n- 입찰서\n- 사업자등록증"
    prompts = []

    _run_answer(draft, "입찰서와 사업자등록증입니다.", query="제출 서류는 무엇인가요?", prompts=prompts)

    required = _required_block(prompts[0])
    assert "입찰서" in required and "사업자등록증" in required


LONG = "제출 서류는 다음과 같습니다.\n" + "\n".join(f"- 서류 {i}호" for i in range(1, 11))


@pytest.mark.parametrize("mode, query, max_lines", [
    ("extractive", "제출 서류는 무엇인가요?", 2),   # 생성형이 아닌 답
    ("generative", "사업범위를 알려주세요", 6),     # 요약 질문은 설명형이라 6줄까지
])
def test_answer_that_skips_polishing_is_limited_even_if_it_is_a_list(mode, query, max_lines):
    prompts = []

    final = _run_answer(LONG, "쓰이면 안 되는 문장", query=query, prompts=prompts, mode=mode)

    assert not prompts
    assert len(final.splitlines()) <= max_lines
    assert "서류 10호" not in final
