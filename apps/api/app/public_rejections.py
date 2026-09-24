"""Aggregation-ready rejection reasons, deliberately excluding request values."""

import logging

_REASONS = {
    "body_too_large",
    "invalid_request",
    "invalid_geometry",
    "quota_reached",
    "quota_unavailable",
}


def record_public_rejection(reason: str) -> None:
    if reason not in _REASONS:
        reason = "invalid_request"
    logging.getLogger("uvicorn.error").info("public_write_rejected reason=%s", reason)
