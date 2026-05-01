"""Orchestrates: discover → checksum → upload → tag → register in DB."""
import json
from pathlib import Path
from datetime import datetime
from db.session import get_conn
from src.ingestion.local_mock import upload_document, compute_checksum, compute_doc_id, LocalGlueCatalog
from src.metadata.auto_tagger import tag_document
from src.metadata.schema import DocumentMetadata
from config.settings import USE_REAL_S3, S3_BUCKET


def ingest_directory(doc_dir: Path, verbose: bool = True) -> list[DocumentMetadata]:
    """Ingest all documents in a directory through the full pipeline."""
    glue = LocalGlueCatalog()
    glue.create_database("lending_catalog")

    doc_files = sorted(
        [f for f in doc_dir.iterdir() if f.is_file() and f.suffix in {".txt", ".pdf", ".docx", ".md"}]
    )

    if verbose:
        print(f"\n  Found {len(doc_files)} documents to ingest from {doc_dir.name}/")

    ingested: list[DocumentMetadata] = []

    with get_conn() as conn:
        for path in doc_files:
            doc_id = compute_doc_id(path)

            # Skip if already ingested (idempotent)
            existing = conn.execute(
                "SELECT doc_id FROM policy_documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if existing:
                if verbose:
                    print(f"    [skip] {path.name} (already ingested)")
                continue

            checksum = compute_checksum(path)
            meta = tag_document(path, doc_id, str(path))
            meta.file_size_bytes = path.stat().st_size
            meta.checksum = checksum

            if USE_REAL_S3:
                # Production: boto3 multipart upload to real S3
                from config.aws_config import s3_client
                from boto3.s3.transfer import TransferConfig
                s3 = s3_client()
                transfer_config = TransferConfig(multipart_threshold=8 * 1024 * 1024)
                key = f"lending-docs/{datetime.now().year}/{datetime.now().month:02d}/{meta.doc_type}/{doc_id}{path.suffix}"
                s3.upload_file(
                    str(path), S3_BUCKET, key,
                    ExtraArgs={"Tagging": "&".join(f"{k}={v}" for k, v in meta.s3_tags().items())},
                    Config=transfer_config,
                )
                meta.s3_key = key
            else:
                meta.s3_key = upload_document(path, meta)

            # Persist to DB
            conn.execute(
                """INSERT OR IGNORE INTO policy_documents
                   (doc_id, source_key, filename, doc_type, file_size_bytes, ingested_at, s3_key, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, str(path), path.name, meta.doc_type,
                 meta.file_size_bytes, meta.ingested_at.isoformat(),
                 meta.s3_key, checksum),
            )
            conn.execute(
                """INSERT OR IGNORE INTO document_tags
                   (doc_id, regulation_refs, loan_types, effective_date, jurisdiction,
                    risk_tier, version, keywords, tag_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id,
                 json.dumps(meta.regulation_refs),
                 json.dumps(meta.loan_types),
                 str(meta.effective_date) if meta.effective_date else None,
                 meta.jurisdiction, meta.risk_tier, meta.version,
                 json.dumps(meta.keywords), "regex"),
            )

            ingested.append(meta)
            if verbose:
                regs = ", ".join(meta.regulation_refs) or "none"
                print(f"    [OK] {path.name:45s} type={meta.doc_type:10s} "
                      f"risk={meta.risk_tier:8s} regs=[{regs}]")

    return ingested
