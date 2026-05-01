"""End-to-end showcase demo — runs all six pillars sequentially."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from config.settings import BASE_DIR, ANTHROPIC_API_KEY
from db.session import init_db, get_conn
from db.seed import seed_all
from src.assessment.scorer import ReadinessScorer
from src.assessment.report import print_report
from src.ingestion.pipeline import ingest_directory
from src.knowledge_base.indexer import index_all_documents
from src.retrieval.query_pipeline import retrieve
from src.agent.agent import LendingComplianceAgent
from config.settings import LOCAL_S3_ROOT


def run_demo() -> None:
    print("\n" + "=" * 65)
    print("  END-TO-END COMMERCIAL LENDING AI READINESS SHOWCASE")
    print("=" * 65)

    # ─── SETUP ────────────────────────────────────────────────────
    init_db()
    seed_all()
    LOCAL_S3_ROOT.mkdir(parents=True, exist_ok=True)

    # ─── PILLAR 1: Data Readiness Assessment ──────────────────────
    print("\n\n── PILLAR 1: DATA READINESS ASSESSMENT ─────────────────────")
    print("   Evaluating CRM, document repository, and compliance DB")
    print("   for AI agent consumption readiness...\n")

    with get_conn() as conn:
        report = ReadinessScorer(conn).score()

    print_report(report)

    # ─── PILLAR 2 + 3: Ingest + Metadata Tag ──────────────────────
    print("\n── PILLAR 2: S3/GLUE INGESTION PIPELINE ────────────────────")
    print("   Discovering, checksumming, uploading, and cataloging")
    print("   policy documents to local S3 mock + Glue catalog...\n")

    doc_dir = BASE_DIR / "data" / "seed" / "policy_documents"
    ingested = ingest_directory(doc_dir, verbose=True)

    print(f"\n── PILLAR 3: METADATA TAGGING RESULTS ──────────────────────")
    print(f"   Auto-tagged {len(ingested)} new documents (regex + TF-IDF passes).")
    print(f"   All tagged documents in knowledge base:\n")
    import json as _json
    with get_conn() as conn:
        tagged_docs = conn.execute(
            """SELECT p.filename, p.doc_type, t.regulation_refs, t.loan_types,
                      t.risk_tier, t.keywords, t.version
               FROM policy_documents p JOIN document_tags t ON p.doc_id = t.doc_id
               ORDER BY p.filename"""
        ).fetchall()
    for row in tagged_docs:
        regs = ", ".join(_json.loads(row["regulation_refs"] or "[]")) or "none"
        loans = ", ".join(_json.loads(row["loan_types"] or "[]")) or "none"
        kw = ", ".join(_json.loads(row["keywords"] or "[]")[:5])
        ver = f" v{row['version']}" if row["version"] else ""
        print(f"   {(row['filename'] or '?'):45s}")
        print(f"     type={row['doc_type']:12s} risk={row['risk_tier']:8s}{ver}")
        print(f"     regs=[{regs}]")
        print(f"     loans=[{loans}]")
        print(f"     keywords=[{kw}]")
        print()

    # ─── PILLAR 4: Index Knowledge Base ───────────────────────────
    print("── PILLAR 4: KNOWLEDGE BASE STRUCTURING ────────────────────")
    print("   Applying HYBRID chunking strategy and indexing embeddings\n")

    total_chunks = index_all_documents(verbose=True)
    with get_conn() as conn:
        doc_count = conn.execute("SELECT COUNT(DISTINCT doc_id) FROM document_chunks").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    print(f"\n   Knowledge base: {chunk_count} chunks across {doc_count} documents")

    # ─── PILLAR 5: RAG Retrieval ───────────────────────────────────
    print("\n── PILLAR 5: RAG RETRIEVAL DEMONSTRATION ───────────────────")
    test_queries = [
        ("DSCR requirements for SBA 504 loans", {"loan_type": "SBA"}),
        ("ECOA adverse action notice timing requirements", {"regulation": "ECOA"}),
        ("beneficial ownership certification requirements", None),
    ]

    for query, filters in test_queries:
        results = retrieve(query, top_k=3, filters=filters)
        print(f"\n   Query: \"{query}\"")
        for i, r in enumerate(results, 1):
            header = f" → {r.section_header}" if r.section_header else ""
            regs = ", ".join(r.regulation_refs) or "general"
            print(f"   [{i}] {r.doc_id}{header}")
            print(f"       score={r.score:.4f} | risk={r.risk_tier} | regs=[{regs}]")
            print(f"       \"{r.text[:120].strip()}...\"")

    # ─── PILLAR 6: Agent Tool Use ──────────────────────────────────
    print("\n\n── PILLAR 6: LENDING COMPLIANCE AGENT (Claude + Tool Use) ──")

    if not ANTHROPIC_API_KEY:
        print("\n   [!] ANTHROPIC_API_KEY not set — skipping live agent demo.")
        print("       Set ANTHROPIC_API_KEY in .env and re-run to see agent in action.")
        _print_agent_summary()
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    agent = LendingComplianceAgent(client)

    queries = [
        "Is borrower CUST-001 eligible for a $1.5M C&I loan? Their NOI is $187,500 and "
        "annual debt service will be $162,000. Collateral appraised at $1.8M.",
        "What are the ECOA requirements I must follow when issuing an adverse action notice "
        "to a commercial borrower?",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n   ── Query {i} ──────────────────────────────────────────────")
        print(f"   User: {query}\n")
        result = agent.run(query, verbose=True)
        print(f"\n   Agent Response:\n")
        print("   " + result.final_response.replace("\n", "\n   "))
        print(f"\n   [Completed in {result.turns} turn(s), {len(result.tool_calls)} tool call(s)]")

    print("\n" + "=" * 65)
    print("  SHOWCASE COMPLETE")
    print("=" * 65 + "\n")


def _print_agent_summary() -> None:
    print("""
   Agent architecture summary (requires ANTHROPIC_API_KEY to run live):
   - Model: claude-sonnet-4-6
   - Tools: query_policy_knowledge_base, lookup_borrower_crm,
            check_compliance_rules, compute_dscr_ltv
   - Loop: Anthropic tool_use → dispatch → ToolResult → repeat until end_turn
   - Max turns: 10 (configurable)
   - System prompt enforces: source citation, compliance-first, human oversight
""")


if __name__ == "__main__":
    run_demo()
