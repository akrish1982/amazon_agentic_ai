"""Orchestrates chunk → embed → store for all ingested documents."""
import json
from db.session import get_conn
from src.knowledge_base.chunker import chunk_document, ChunkStrategy
from src.knowledge_base.embedder import embed
from src.knowledge_base.vector_store import upsert_chunk
from src.metadata.schema import DocumentMetadata
from datetime import datetime


def _load_metadata_from_db(conn, doc_id: str) -> DocumentMetadata | None:
    doc = conn.execute(
        "SELECT * FROM policy_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if not doc:
        return None
    tags = conn.execute(
        "SELECT * FROM document_tags WHERE doc_id = ?", (doc_id,)
    ).fetchone()

    return DocumentMetadata(
        doc_id=doc["doc_id"],
        source_key=doc["source_key"],
        doc_type=doc["doc_type"] or "policy",
        ingested_at=datetime.fromisoformat(doc["ingested_at"]),
        regulation_refs=json.loads(tags["regulation_refs"] or "[]") if tags else [],
        loan_types=json.loads(tags["loan_types"] or "[]") if tags else [],
        risk_tier=tags["risk_tier"] or "medium" if tags else "medium",
        version=tags["version"] or "" if tags else "",
        keywords=json.loads(tags["keywords"] or "[]") if tags else [],
        s3_key=doc["s3_key"] or "",
        file_size_bytes=doc["file_size_bytes"] or 0,
        checksum=doc["checksum"] or "",
    )


def index_document(doc_id: str, text: str, verbose: bool = False) -> int:
    """Chunk, embed, and store all chunks for a single document. Returns chunk count."""
    with get_conn() as conn:
        meta = _load_metadata_from_db(conn, doc_id)
        if not meta:
            raise ValueError(f"Document {doc_id} not found in policy_documents table")

        already_indexed = conn.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE doc_id = ?", (doc_id,)
        ).fetchone()[0]
        if already_indexed > 0:
            return already_indexed

        chunks = chunk_document(text, meta, strategy=ChunkStrategy.HYBRID)

        for chunk in chunks:
            embedding = embed(chunk.text)
            upsert_chunk(
                conn,
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                section_header=chunk.section_header,
                embedding=embedding,
            )

        if verbose:
            print(f"    Indexed {len(chunks)} chunks for {doc_id}")
        return len(chunks)


def index_all_documents(verbose: bool = True) -> int:
    """Index every document in policy_documents that hasn't been indexed yet."""
    import pathlib
    total_chunks = 0

    with get_conn() as conn:
        docs = conn.execute(
            """SELECT p.doc_id, p.source_key
               FROM policy_documents p
               WHERE p.doc_id NOT IN (SELECT DISTINCT doc_id FROM document_chunks)"""
        ).fetchall()

    if verbose:
        print(f"\n  Indexing {len(docs)} unindexed documents...")

    for doc in docs:
        path = pathlib.Path(doc["source_key"])
        if not path.exists():
            if verbose:
                print(f"    [skip] {doc['doc_id']} — source file not found at {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        count = index_document(doc["doc_id"], text, verbose=verbose)
        total_chunks += count

    if verbose:
        print(f"  Total chunks indexed: {total_chunks}")

    return total_chunks
