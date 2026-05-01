"""
Amazon Bedrock Knowledge Base integration.
Activated when settings.USE_BEDROCK_KB = True.

Production pattern for 100K+ documents:
  1. Documents live in S3 (uploaded via ingestion/pipeline.py)
  2. Bedrock KB syncs from S3, chunks, and embeds using Titan
  3. Retrieval uses Bedrock Agent Runtime retrieve() API
  4. Metadata filtering uses S3 object tags propagated to KB
"""
import json
from config.aws_config import bedrock_agent_client
from config.settings import AWS_REGION

KB_ID = "your-bedrock-kb-id"   # Set via environment or Terraform output


def retrieve_from_bedrock_kb(
    query: str,
    top_k: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """
    Real Bedrock Knowledge Base retrieval.

    filter example:
        filters = {"andAll": [
            {"equals": {"key": "loan_type", "value": "SBA"}},
            {"equals": {"key": "risk_tier", "value": "critical"}},
        ]}
    """
    client = bedrock_agent_client()

    retrieval_config = {
        "vectorSearchConfiguration": {
            "numberOfResults": top_k,
            "overrideSearchType": "HYBRID",  # semantic + keyword
        }
    }
    if filters:
        retrieval_config["vectorSearchConfiguration"]["filter"] = filters

    response = client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration=retrieval_config,
    )

    return [
        {
            "text": r["content"]["text"],
            "score": r["score"],
            "location": r["location"],
            "metadata": r.get("metadata", {}),
        }
        for r in response.get("retrievalResults", [])
    ]


def sync_knowledge_base() -> str:
    """Trigger a Bedrock KB sync from S3 (runs asynchronously)."""
    import boto3
    from config.aws_config import get_session
    client = get_session().client("bedrock-agent")
    response = client.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId="your-datasource-id",
    )
    job_id = response["ingestionJob"]["ingestionJobId"]
    return f"Ingestion job started: {job_id}"
