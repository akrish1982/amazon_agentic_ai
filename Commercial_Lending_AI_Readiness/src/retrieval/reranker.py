"""MMR reranker with metadata-based boosts."""
import math
from datetime import date
from src.knowledge_base.vector_store import SearchResult

MMR_LAMBDA = 0.7  # relevance vs diversity trade-off


def _cosine_texts(a_score: float, b_score: float) -> float:
    # Approximate inter-result similarity via score proximity
    return 1.0 - abs(a_score - b_score)


def mmr_rerank(
    candidates: list[SearchResult],
    top_k: int,
    lambda_: float = MMR_LAMBDA,
) -> list[SearchResult]:
    """Maximal Marginal Relevance: balance relevance and diversity."""
    if not candidates:
        return []

    selected: list[SearchResult] = []
    remaining = list(candidates)

    while remaining and len(selected) < top_k:
        if not selected:
            # First pick: highest relevance
            best = max(remaining, key=lambda r: _boosted_score(r))
        else:
            # Subsequent picks: maximize λ*relevance - (1-λ)*max_similarity_to_selected
            def mmr_score(r: SearchResult) -> float:
                rel = _boosted_score(r)
                max_sim = max(
                    _inter_chunk_similarity(r, s) for s in selected
                )
                return lambda_ * rel - (1 - lambda_) * max_sim

            best = max(remaining, key=mmr_score)

        selected.append(best)
        remaining.remove(best)

    return selected


def _boosted_score(result: SearchResult) -> float:
    """Apply metadata-based relevance boosts."""
    score = result.score
    if result.risk_tier == "critical":
        score += 0.10
    elif result.risk_tier == "high":
        score += 0.05
    return min(score, 1.0)


def _inter_chunk_similarity(a: SearchResult, b: SearchResult) -> float:
    """Heuristic inter-chunk similarity: same doc = high similarity."""
    if a.doc_id == b.doc_id:
        # Penalize selecting multiple chunks from the same doc
        return 0.8
    return 0.1
