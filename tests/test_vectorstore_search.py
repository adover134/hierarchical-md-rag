"""`VectorStore.search`의 후보 풀, 어휘 점수 질의, 기관 필터 위치 테스트. Chroma와 임베딩 모델 없이 후보 조회만 가짜로 바꿔 쓴다."""

import pytest

from src.retrievers.vectorstore import VectorStore


def _store(rows, count):
    """`_query_candidates`가 rows를 (요청한 개수만큼, where가 있으면 그 기관만) 돌려주는 가짜 저장소."""
    store = object.__new__(VectorStore)
    store.count = count
    store.calls = []

    def fake_query(query, n_results, where=None):
        store.calls.append({"query": query, "n_results": n_results, "where": where})
        picked = [r for r in rows if not where or r["metadata"].get("org") == where["org"]]
        return picked[:n_results]

    store._query_candidates = fake_query
    return store


def _row(i, text, org="A", distance=0.5):
    return {"id": f"c{i}", "text": text, "metadata": {"org": org, "source": "s"}, "source": "s",
            "page": 1, "distance": distance, "chunk_id": f"c{i}", "chunk_index": i}


ROWS = [_row(0, "입찰 유의사항 자격 요건", distance=0.4), _row(1, "공사기간: 착공일로부터 120일", distance=0.8)]


class TestLexicalQuery:
    def test_lexical_score_uses_the_lexical_query_when_given(self):
        store = _store(ROWS, count=2)
        # 원문 질의의 `공사기간은`은 청크의 `공사기간`과 겹치지 않는다. 조사를 뗀 질의를 넘기면 겹친다.
        plain = store.search("공사기간은 며칠인가요", top_k=2, mode="hybrid")
        keyed = store.search("공사기간은 며칠인가요", top_k=2, mode="hybrid", lexical_query="공사기간 며칠")
        lex = lambda res, i: next(r["lexical_score"] for r in res if r["id"] == f"c{i}")
        assert lex(plain, 1) == 0.0
        assert lex(keyed, 1) > 0.0

    def test_dense_query_is_still_the_original(self):
        store = _store(ROWS, count=2)
        store.search("공사기간은 며칠인가요", top_k=2, mode="hybrid", lexical_query="공사기간 며칠")
        assert store.calls[0]["query"] == "공사기간은 며칠인가요"


class TestCandidatePool:
    def test_small_database_is_searched_in_full_only_when_enabled(self, monkeypatch):
        import src.retrievers.vectorstore as vs

        monkeypatch.setattr(vs, "RETRIEVAL_FULL_POOL_MAX", 2000)
        store = _store(ROWS, count=1207)
        store.search("q", top_k=24, mode="hybrid")
        assert store.calls[0]["n_results"] == 1207

    def test_default_pool_is_proportional_not_the_whole_database(self):
        store = _store(ROWS, count=1207)
        store.search("q", top_k=24, mode="hybrid")
        assert store.calls[0]["n_results"] == 360

    def test_large_database_keeps_the_proportional_pool(self, monkeypatch):
        import src.retrievers.vectorstore as vs

        monkeypatch.setattr(vs, "RETRIEVAL_FULL_POOL_MAX", 2000)
        store = _store(ROWS, count=50000)
        store.search("q", top_k=24, mode="hybrid")
        assert store.calls[0]["n_results"] == 360

    def test_explicit_candidate_k_wins(self):
        store = _store(ROWS, count=1207)
        store.search("q", top_k=24, mode="hybrid", candidate_k=40)
        assert store.calls[0]["n_results"] == 40


class TestOrgFilterBeforeCut:
    @pytest.fixture(autouse=True)
    def _pool_covers_only_small_dbs(self, monkeypatch):
        import src.retrievers.vectorstore as vs

        monkeypatch.setattr(vs, "RETRIEVAL_FULL_POOL_MAX", 100)
        monkeypatch.setattr(vs, "RETRIEVAL_ORG_PREFILTER", True)

    def test_org_filter_is_passed_to_the_candidate_query_for_a_large_db(self):
        store = _store(ROWS, count=5000)
        store.search("q", top_k=5, mode="hybrid", org_name="A")
        assert store.calls[0]["where"] == {"org": "A"}

    def test_no_org_means_no_filter(self):
        store = _store(ROWS, count=5000)
        store.search("q", top_k=5, mode="hybrid")
        assert store.calls[0]["where"] is None

    def test_prefilter_is_off_unless_enabled(self, monkeypatch):
        import src.retrievers.vectorstore as vs

        monkeypatch.setattr(vs, "RETRIEVAL_ORG_PREFILTER", False)
        store = _store(ROWS, count=5000)
        store.search("q", top_k=5, mode="hybrid", org_name="A")
        assert store.calls[0]["where"] is None

    def test_small_db_whose_pool_covers_everything_does_not_prefilter(self):
        store = _store(ROWS, count=50)
        store.search("q", top_k=5, mode="hybrid", org_name="A")
        assert store.calls[0]["where"] is None

    def test_target_org_chunk_survives_when_it_would_have_been_cut(self):
        other = [_row(i, "다른 공고 내용", org="B", distance=0.1) for i in range(10)]
        mine = [_row(99, "공사기간: 착공일로부터 120일", org="A", distance=0.9)]
        store = _store(other + mine, count=5000)
        # 필터 없이 상위 3개만 자르면 A의 청크는 사라지고, 기관 필터를 먼저 걸면 남는다
        assert all(r["metadata"]["org"] == "B" for r in store.search("q", top_k=3, mode="chroma", candidate_k=3))
        assert [r["id"] for r in store.search("q", top_k=3, mode="chroma", candidate_k=3, org_name="A")] == ["c99"]
