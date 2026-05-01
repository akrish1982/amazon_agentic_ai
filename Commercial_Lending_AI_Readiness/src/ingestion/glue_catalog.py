"""
AWS Glue Data Catalog integration.
Activated when settings.USE_REAL_GLUE = True.

Creates a Glue database and table for the policy_documents metadata,
enabling Athena queries across 100K+ ingested documents.
"""
from config.aws_config import glue_client
from config.settings import GLUE_DATABASE, S3_BUCKET

_DOCUMENT_SCHEMA = [
    {"Name": "doc_id",          "Type": "string"},
    {"Name": "source_key",      "Type": "string"},
    {"Name": "doc_type",        "Type": "string"},
    {"Name": "regulation_refs", "Type": "array<string>"},
    {"Name": "loan_types",      "Type": "array<string>"},
    {"Name": "risk_tier",       "Type": "string"},
    {"Name": "version",         "Type": "string"},
    {"Name": "effective_date",  "Type": "date"},
    {"Name": "keywords",        "Type": "array<string>"},
    {"Name": "ingested_at",     "Type": "timestamp"},
    {"Name": "file_size_bytes", "Type": "bigint"},
    {"Name": "checksum",        "Type": "string"},
]


def ensure_catalog() -> None:
    glue = glue_client()

    try:
        glue.create_database(
            DatabaseInput={
                "Name": GLUE_DATABASE,
                "Description": "Lending AI policy document catalog",
            }
        )
    except glue.exceptions.AlreadyExistsException:
        pass

    try:
        glue.create_table(
            DatabaseName=GLUE_DATABASE,
            TableInput={
                "Name": "policy_documents",
                "Description": "Ingested lending policy documents with AI-ready metadata",
                "StorageDescriptor": {
                    "Columns": _DOCUMENT_SCHEMA,
                    "Location": f"s3://{S3_BUCKET}/lending-docs/",
                    "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                    "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    "SerdeInfo": {
                        "SerializationLibrary": "org.apache.hive.hcatalog.data.JsonSerDe",
                    },
                },
                "TableType": "EXTERNAL_TABLE",
                "Parameters": {
                    "classification": "json",
                    "compressionType": "none",
                },
            },
        )
    except glue.exceptions.AlreadyExistsException:
        pass
