"""
Production S3 uploader using boto3 multipart transfer.
Activated when settings.USE_REAL_S3 = True.

Key strategy: s3://{bucket}/lending-docs/{year}/{month}/{doc_type}/{doc_id}.{ext}
"""
from pathlib import Path
from datetime import datetime
import boto3
from boto3.s3.transfer import TransferConfig
from config.aws_config import s3_client
from config.settings import S3_BUCKET
from src.metadata.schema import DocumentMetadata

_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=8 * 1024 * 1024,   # 8 MB threshold
    max_concurrency=10,
    multipart_chunksize=8 * 1024 * 1024,
    use_threads=True,
)


def upload(source_path: Path, meta: DocumentMetadata) -> str:
    """Upload document to S3 with metadata tags. Returns the S3 key."""
    now = meta.ingested_at
    ext = source_path.suffix or ".txt"
    key = f"lending-docs/{now.year}/{now.month:02d}/{meta.doc_type}/{meta.doc_id}{ext}"

    s3 = s3_client()
    s3.upload_file(
        Filename=str(source_path),
        Bucket=S3_BUCKET,
        Key=key,
        ExtraArgs={
            "ServerSideEncryption": "AES256",
            "Tagging": _encode_tags(meta.s3_tags()),
            "Metadata": {
                "doc-id": meta.doc_id,
                "ingested-at": now.isoformat(),
                "checksum": meta.checksum,
            },
        },
        Config=_TRANSFER_CONFIG,
    )
    return key


def _encode_tags(tags: dict[str, str]) -> str:
    """URL-encode S3 object tags."""
    from urllib.parse import urlencode
    return urlencode(tags)
