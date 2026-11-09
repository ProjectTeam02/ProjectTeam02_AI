from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

DOWNLOADS = (
    ("BOK_TERMS_S3_URI", "BOK_TERMS_PATH"),
    ("BOK_SOURCE_S3_URI", "BOK_SOURCE_PATH"),
    ("QUESTION_EVIDENCE_S3_URI", "QUESTION_EVIDENCE_PATH"),
    ("QUESTION_APPROVAL_LABEL_S3_URI", "QUESTION_APPROVAL_LABEL_PATH"),
)


def main() -> None:
    configured = [item for item in DOWNLOADS if os.getenv(item[0])]
    if not configured:
        return

    # Import lazily so local Docker/pytest runs do not need AWS credentials or
    # an active S3 connection when no S3 URI is configured.
    import boto3

    client = boto3.client("s3")
    for source_name, target_name in configured:
        uri = os.environ[source_name]
        target = Path(os.environ[target_name])
        bucket, key = _parse_s3_uri(uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(target))


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"invalid S3 URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


if __name__ == "__main__":
    main()
