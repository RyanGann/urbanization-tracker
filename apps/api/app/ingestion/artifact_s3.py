"""Private S3-compatible multipart transport with portable GET verification."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def validate_s3_configuration(
    *,
    endpoint: str,
    bucket: str,
    region: str,
    access_key: str,
    secret_key: str,
    allow_http: bool = False,
) -> None:
    """Validate sink configuration without creating a client or making a network call."""
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port  # urlsplit defers malformed/out-of-range port validation.
    except ValueError:
        raise ArtifactError("artifact_configuration") from None
    if (
        parsed.scheme not in ({"https", "http"} if allow_http else {"https"})
        or not parsed.hostname
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127
               for character in endpoint)
        or not _valid_endpoint_host(parsed.hostname, parsed.netloc)
        or port == 0
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not _valid_bucket_name(bucket)
        or not re.fullmatch(r"[a-zA-Z0-9-]+", region)
        or not access_key
        or not secret_key
    ):
        raise ArtifactError("artifact_configuration")


def _valid_endpoint_host(hostname: str, netloc: str) -> bool:
    """Accept DNS/IDNA, IPv4 and bracketed IPv6 syntax without DNS/network I/O."""
    if "%" in hostname or "@" in netloc:
        return False
    if netloc.startswith("["):
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", netloc):
            return False
        try:
            return isinstance(ipaddress.ip_address(hostname), ipaddress.IPv6Address)
        except ValueError:
            return False
    if not re.fullmatch(r"[^:/?#@\[\]\\]+(?::[0-9]+)?", netloc):
        return False
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", hostname):
        try:
            ipaddress.IPv4Address(hostname)
        except ipaddress.AddressValueError:
            return False
        return True
    try:
        ascii_host = hostname.encode("idna").decode("ascii").removesuffix(".")
        if not ascii_host or len(ascii_host) > 253:
            return False
        for label in ascii_host.split("."):
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label):
                return False
            if label.startswith("xn--"):
                # The codec does not validate already-ASCII punycode on encode.
                label.encode("ascii").decode("idna")
    except UnicodeError:
        return False
    return True


def _valid_bucket_name(bucket: str) -> bool:
    """Use the portable DNS-compatible S3 general-purpose bucket subset."""
    if not 3 <= len(bucket) <= 63 or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]*[a-z0-9]", bucket
    ):
        return False
    if any(fragment in bucket for fragment in ("..", ".-", "-.")):
        return False
    if bucket.startswith(("xn--", "sthree-", "amzn-s3-demo-")) or bucket.endswith(
        ("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")
    ):
        return False
    try:
        ipaddress.IPv4Address(bucket)
    except ipaddress.AddressValueError:
        return True
    return False


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
        validate_s3_configuration(
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
            allow_http=allow_http,
        )
        self.endpoint = endpoint.rstrip("/")
        # Preserve every existing ASCII sink identity, including casing and
        # port spelling. Previously unusable Unicode IDNA hosts normalize to
        # ASCII for both client construction and their new sink identity.
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
        assert hostname is not None
        if not hostname.isascii():
            host = hostname.encode("idna").decode("ascii")
            netloc = host if parsed.port is None else f"{host}:{parsed.port}"
            self.endpoint = urlunsplit((parsed.scheme, netloc, "", "", ""))
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
