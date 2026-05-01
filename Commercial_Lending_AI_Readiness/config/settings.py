import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")
S3_BUCKET = os.getenv("S3_BUCKET", "lending-ai-docs")
GLUE_DATABASE = os.getenv("GLUE_DATABASE", "lending_catalog")

USE_BEDROCK_KB = os.getenv("USE_BEDROCK_KB", "false").lower() == "true"
USE_BEDROCK_EMBEDDINGS = os.getenv("USE_BEDROCK_EMBEDDINGS", "false").lower() == "true"
USE_REAL_S3 = os.getenv("USE_REAL_S3", "false").lower() == "true"
USE_REAL_GLUE = os.getenv("USE_REAL_GLUE", "false").lower() == "true"

LOCAL_S3_ROOT = BASE_DIR / os.getenv("LOCAL_S3_ROOT", "data/local_s3")
LOCAL_DB_PATH = BASE_DIR / os.getenv("LOCAL_DB_PATH", "data/lending_ai.db")

CLAUDE_MODEL = "claude-sonnet-4-6"
BEDROCK_EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 1536

CHUNK_MAX_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 64
RETRIEVAL_TOP_K = 5
MMR_LAMBDA = 0.7
