"""Tool: query_policy_knowledge_base — searches the indexed lending policy KB."""
from src.retrieval.query_pipeline import retrieve, build_context


def query_policy_knowledge_base(
    query: str,
    loan_type: str = "all",
    regulation: str = "",
    top_k: int = 5,
) -> str:
    filters: dict = {}
    if loan_type and loan_type != "all":
        filters["loan_type"] = loan_type
    if regulation:
        filters["regulation"] = regulation.upper()

    results = retrieve(query, top_k=top_k, filters=filters or None)

    if not results:
        return "No relevant policy documents found for this query."

    context = build_context(results)
    summary_lines = [
        f"Retrieved {len(results)} relevant policy chunks:\n"
    ]
    for i, r in enumerate(results, 1):
        header = f" — {r.section_header}" if r.section_header else ""
        regs = ", ".join(r.regulation_refs) if r.regulation_refs else "general"
        summary_lines.append(
            f"[{i}] {r.doc_id}{header} (relevance: {r.score:.3f}, regs: {regs})"
        )

    return "\n".join(summary_lines) + "\n\n" + context
