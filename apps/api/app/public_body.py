"""Count public write bodies before JSON parsing, including chunked requests."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.public_rejections import record_public_rejection

PUBLIC_WRITE_PATHS = {"/api/public-submissions", "/api/watch-areas"}
MAX_PUBLIC_BODY_BYTES = 256 * 1024


def excessive_json_nesting(body: bytearray) -> bool:
    depth = 0
    quoted = escaped = False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 32:
                return True
        elif byte in (93, 125):
            depth -= 1
    return False


class PublicWriteBodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/") not in PUBLIC_WRITE_PATHS
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_PUBLIC_BODY_BYTES:
                record_public_rejection("body_too_large")
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "body_too_large",
                            "message": "Request exceeds the 256 KiB limit.",
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        try:
            decoded = body.decode("utf-8")
            invalid_encoding = "\x00" in decoded
        except UnicodeDecodeError:
            invalid_encoding = True
        if invalid_encoding or excessive_json_nesting(body):
            record_public_rejection("invalid_request")
            response = JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "invalid_request",
                        "message": "Use UTF-8 JSON with at most 32 nested levels.",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
