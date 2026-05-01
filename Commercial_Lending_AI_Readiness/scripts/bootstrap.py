"""One-shot setup: initialize DB + seed + ingest docs + index knowledge base."""
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.session import init_db
from db.seed import seed_all
from src.ingestion.pipeline import ingest_directory
from src.knowledge_base.indexer import index_all_documents
from config.settings import BASE_DIR, LOCAL_S3_ROOT


def bootstrap() -> None:
    print("\n" + "=" * 60)
    print("  LENDING AI SYSTEM — BOOTSTRAP")
    print("=" * 60)

    print("\n[1/4] Initializing database schema...")
    init_db()
    print("      Done.")

    print("\n[2/4] Seeding CRM, compliance rules, and loan data...")
    seed_all()

    print("\n[3/4] Ingesting policy documents (S3 mock + metadata tagging)...")
    LOCAL_S3_ROOT.mkdir(parents=True, exist_ok=True)
    doc_dir = BASE_DIR / "data" / "seed" / "policy_documents"
    ingested = ingest_directory(doc_dir, verbose=True)
    print(f"\n      Ingested {len(ingested)} documents.")

    print("\n[4/4] Chunking and indexing knowledge base...")
    total_chunks = index_all_documents(verbose=True)
    print(f"\n      Knowledge base ready: {total_chunks} chunks indexed.")

    print("\n" + "=" * 60)
    print("  Bootstrap complete. Run: python scripts/run_demo.py")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    bootstrap()
