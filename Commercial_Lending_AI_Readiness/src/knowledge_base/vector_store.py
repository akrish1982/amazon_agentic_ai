"""SQLite-backed local vector store with pure-Python cosine similarity."""
import json
import math
import sqlite3
from dataclasses import dataclass
from db.session import get_conn


@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    score: float
    text: str
    section_header: str | None
    regulation_refs: list[str]
    loan_types: list[str]
    risk_tier: str


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    denom = norm_a * norm_b
    return dot / denom if denom else 0.0


def upsert_chunk(
    conn: sqlite3.Connection,
    chunk_id: str,
    doc_id: str,
    chunk_index: int,
    text: str,
    token_count: int,
    section_header: str | None,
    embedding: list[float],
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO document_chunks
           (chunk_id, doc_id, chunk_index, text, token_count, section_header, embedding)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (chunk_id, doc_id, chunk_index, text, token_count,
         section_header, json.dumps(embedding)),
    )


def search(
    query_embedding: list[float],
    top_k: int = 15,
    filters: dict | None = None,
) -> list[SearchResult]:
    """Scan all chunks, compute cosine similarity, apply metadata filters, return top_k."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.chunk_id, c.doc_id, c.text, c.section_header, c.embedding,
                      t.regulation_refs, t.loan_types, t.risk_tier
               FROM document_chunks c
               LEFT JOIN document_tags t ON c.doc_id = t.doc_id
               WHERE c.embedding IS NOT NULL"""
        ).fetchall()

    results: list[SearchResult] = []
    for row in rows:
        embedding = json.loads(row["embedding"])
        score = _cosine(query_embedding, embedding)

        reg_refs = json.loads(row["regulation_refs"] or "[]")
        loan_types = json.loads(row["loan_types"] or "[]")
        risk_tier = row["risk_tier"] or "medium"

        # Apply metadata filters
        if filters:
            if "regulation" in filters and filters["regulation"] not in reg_refs:
                continue
            if "loan_type" in filters and filters["loan_type"] not in loan_types:
                continue
            if "risk_tier" in filters and risk_tier != filters["risk_tier"]:
                continue

        results.append(SearchResult(
            chunk_id=row["chunk_id"],
            doc_id=row["doc_id"],
            score=score,
            text=row["text"],
            section_header=row["section_header"],
            regulation_refs=reg_refs,
            loan_types=loan_types,
            risk_tier=risk_tier,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
