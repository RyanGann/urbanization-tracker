"""Private S3-compatible multipart transport with portable GET verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.ingestion.artifact_sink import (
    CHUNK_BYTES,
    ArtifactError,
    BlobIdentity,
    UploadedPart,
    validate_part,
    validate_parts,
)


class S3ArtifactSink:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        allow_http: bool = False,
    ) -> None:
        try:
            parsed = urlsplit(endpoint)
        except ValueError:
            raise ArtifactError("artifact_configuration") from None
        if (
            parsed.scheme not in ({"https", "http"} if allow_http else {"https"})
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not bucket
            or len(bucket) > 63
            or not region
            or not access_key
            or not secret_key
        ):
            raise ArtifactError("artifact_configuration")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.region = region
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 2},
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    @property
    def fingerprint(self) -> str:
        identity = ["s3-v1", self.endpoint, self.bucket, self.region]
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()

    def _call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        try:
            result: dict[str, Any] = getattr(self.client, operation)(Bucket=self.bucket, **kwargs)
            return result
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ArtifactError("artifact_missing") from None
            if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403"}:
                raise ArtifactError("artifact_credentials") from None
            if code == "NoSuchUpload":
                raise ArtifactError("artifact_checkpoint") from None
            raise ArtifactError("artifact_unavailable") from None
        except BotoCoreError:
            raise ArtifactError("artifact_unavailable") from None

    def size(self, blob: BlobIdentity) -> int:
        result = self._call("head_object", Key=blob.key)
        return int(result["ContentLength"])

    def read(self, blob: BlobIdentity) -> Iterator[bytes]:
        result = self._call("get_object", Key=blob.key)
        body = result["Body"]
        try:
            while chunk := body.read(CHUNK_BYTES):
                yield chunk
        except (BotoCoreError, OSError):
            raise ArtifactError("artifact_unavailable") from None
        finally:
            body.close()

    def begin(self, blob: BlobIdentity) -> str:
        if blob.byte_size == 0:
            return "empty-object-v1"
        result = self._call(
            "create_multipart_upload",
            Key=blob.key,
            ContentType="application/octet-stream",
            Metadata={"sha256": blob.sha256},
        )
        return str(result["UploadId"])

    def upload_part(
        self, blob: BlobIdentity, upload_id: str, number: int, data: bytes
    ) -> UploadedPart:
        validate_part(number, data, blob)
        if blob.byte_size == 0:
            return UploadedPart(1, "empty-object-v1", hashlib.sha256(b"").hexdigest(), 0)
        result = self._call(
            "upload_part",
            Key=blob.key,
            UploadId=upload_id,
            PartNumber=number,
            Body=data,
        )
        return UploadedPart(
            number, str(result["ETag"]), hashlib.sha256(data).hexdigest(), len(data)
        )

    def complete(self, blob: BlobIdentity, upload_id: str, parts: tuple[UploadedPart, ...]) -> None:
        validate_parts(parts, blob)
        if blob.byte_size == 0:
            self._call(
                "put_object",
                Key=blob.key,
                Body=b"",
                ContentType="application/octet-stream",
                Metadata={"sha256": blob.sha256},
            )
            return
        self._call(
            "complete_multipart_upload",
            Key=blob.key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [{"PartNumber": part.number, "ETag": part.etag} for part in parts]
            },
        )

    def abort(self, blob: BlobIdentity, upload_id: str) -> None:
        if blob.byte_size == 0:
            return
        self._call("abort_multipart_upload", Key=blob.key, UploadId=upload_id)
