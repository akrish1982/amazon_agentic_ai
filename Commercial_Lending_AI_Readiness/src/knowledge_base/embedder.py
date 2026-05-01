"""Embedder: deterministic local mock + Amazon Bedrock Titan stub."""
import hashlib
import math
import json
from config.settings import EMBED_DIM, USE_BEDROCK_EMBEDDINGS


def _local_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic pseudo-embedding for demo use — reproducible, no API call."""
    seed = hashlib.sha256(text.encode()).digest()
    values = []
    i = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        for byte in block:
            values.append((byte / 127.5) - 1.0)  # normalize to [-1, 1]
        i += 1
    raw = values[:dim]
    # L2 normalize so cosine similarity = dot product
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def _bedrock_embed(text: str) -> list[float]:
    from config.aws_config import bedrock_client
    client = bedrock_client()
    response = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIM}),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    return body["embedding"]


def embed(text: str) -> list[float]:
    if USE_BEDROCK_EMBEDDINGS:
        return _bedrock_embed(text)
    return _local_embed(text)
