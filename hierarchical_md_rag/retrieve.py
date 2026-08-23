"""임베딩 + 코사인 유사도 검색. 벡터DB 없이 numpy in-memory로 처리한다 — 비교 실험용 소규모
데이터셋(문서 수십 개)에는 벡터DB가 과하고, 검색 로직이 블랙박스에 안 숨어야 결과를 감사하기
쉽다."""

from __future__ import annotations

import numpy as np

_DEFAULT_MODEL = "intfloat/multilingual-e5-small"

_model_cache: dict[str, object] = {}


def get_embedder(model_name: str = _DEFAULT_MODEL):
    if model_name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def embed_texts(texts: list[str], model_name: str = _DEFAULT_MODEL) -> np.ndarray:
    """`intfloat/multilingual-e5-*` 계열은 "query: "/"passage: " 프리픽스를 붙여야 성능이
    제대로 나온다(모델 카드 권장 사항) — 여기선 저장 대상(청크)은 passage로 취급한다."""
    embedder = get_embedder(model_name)
    prefixed = [f"passage: {t}" for t in texts]
    vecs = embedder.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs)


def embed_query(query: str, model_name: str = _DEFAULT_MODEL) -> np.ndarray:
    embedder = get_embedder(model_name)
    vec = embedder.encode([f"query: {query}"], normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vec)[0]


def search(query_vec: np.ndarray, chunk_vecs: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    """코사인 유사도 상위 top_k를 (인덱스, 점수) 리스트로 반환. 임베딩이 이미 정규화돼 있으므로
    내적이 곧 코사인 유사도."""
    scores = chunk_vecs @ query_vec
    order = np.argsort(-scores)[:top_k]
    return [(int(i), float(scores[i])) for i in order]
