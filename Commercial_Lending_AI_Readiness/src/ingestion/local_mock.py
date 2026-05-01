"""Local filesystem mock satisfying the same interface as the real S3/Glue pipeline."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from config.settings import LOCAL_S3_ROOT
from src.metadata.schema import DocumentMetadata


def _s3_key(meta: DocumentMetadata) -> str:
    """Mirror the production S3 key strategy."""
    now = meta.ingested_at
    ext = Path(meta.source_key).suffix or ".txt"
    return f"lending-docs/{now.year}/{now.month:02d}/{meta.doc_type}/{meta.doc_id}{ext}"


def upload_document(source_path: Path, meta: DocumentMetadata) -> str:
    """Copy file to local S3 root under the canonical key structure."""
    key = _s3_key(meta)
    dest = LOCAL_S3_ROOT / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest)

    # Write a companion .meta.json (mirrors S3 object tags)
    meta_path = dest.with_suffix(dest.suffix + ".meta.json")
    meta_path.write_text(json.dumps({
        "doc_id": meta.doc_id,
        "s3_key": key,
        "doc_type": meta.doc_type,
        "ingested_at": meta.ingested_at.isoformat(),
        "s3_tags": meta.s3_tags(),
    }, indent=2))

    return key


def compute_checksum(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_doc_id(path: Path) -> str:
    """Stable content-addressable ID."""
    return compute_checksum(path)[:16]


class LocalGlueCatalog:
    """Logs what AWS Glue would do; no-op in local mode."""

    def create_database(self, name: str) -> None:
        print(f"    [Glue mock] Would create database: {name}")

    def register_table(self, database: str, table: str, schema: dict) -> None:
        print(f"    [Glue mock] Would register table {database}.{table} with {len(schema)} columns")
