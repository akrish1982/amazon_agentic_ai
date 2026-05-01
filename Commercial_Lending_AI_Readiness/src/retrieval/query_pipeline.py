"""QueryPipeline: expand → embed → search → rerank → build context."""
import re
from src.knowledge_base.embedder import embed
from src.knowledge_base.vector_store import search, SearchResult
from src.retrieval.reranker import mmr_rerank
from config.settings import RETRIEVAL_TOP_K

_REGULATION_EXTRACT = re.compile(
    r"\b(ECOA|BSA|AML|SBA|CRA|TILA|RESPA|OFAC)\b", re.I
)
_LOAN_TYPE_EXTRACT = re.compile(
    r"\b(SBA 504|SBA 7\(a\)|CRE|C&I|construction|commercial real estate)\b", re.I
)


def _expand_query(query: str) -> str:
    """Prepend extracted regulation and loan type context to boost recall."""
    regs = list(dict.fromkeys(_REGULATION_EXTRACT.findall(query)))
    loan_types = list(dict.fromkeys(_LOAN_TYPE_EXTRACT.findall(query)))
    prefix = " ".join(regs + loan_types)
    return f"{prefix} {query}".strip() if prefix else query


def retrieve(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    filters: dict | None = None,
) -> list[SearchResult]:
    expanded = _expand_query(query)
    query_embedding = embed(expanded)
    # Over-fetch by 3x for MMR reranking
    candidates = search(query_embedding, top_k=top_k * 3, filters=filters)
    return mmr_rerank(candidates, top_k=top_k)


def build_context(results: list[SearchResult]) -> str:
    """Assemble retrieved chunks into XML-tagged context for the system prompt."""
    parts = ["<policy_context>"]
    for r in results:
        regs = ",".join(r.regulation_refs) if r.regulation_refs else "general"
        loans = ",".join(r.loan_types) if r.loan_types else "all"
        section = f' section="{r.section_header}"' if r.section_header else ""
        parts.append(
            f'  <source doc_id="{r.doc_id}"{section} '
            f'regulation_refs="{regs}" loan_types="{loans}" '
            f'risk_tier="{r.risk_tier}" relevance="{r.score:.3f}">\n'
            f'    {r.text.strip()}\n'
            f'  </source>'
        )
    parts.append("</policy_context>")
    return "\n".join(parts)
