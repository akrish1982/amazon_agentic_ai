import boto3
from botocore.config import Config
from config.settings import AWS_REGION, AWS_PROFILE

_retry_config = Config(
    region_name=AWS_REGION,
    retries={"max_attempts": 3, "mode": "adaptive"},
)


def get_session() -> boto3.Session:
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def s3_client():
    return get_session().client("s3", config=_retry_config)


def glue_client():
    return get_session().client("glue", config=_retry_config)


def bedrock_client():
    return get_session().client("bedrock-runtime", config=_retry_config)


def bedrock_agent_client():
    return get_session().client("bedrock-agent-runtime", config=_retry_config)
