from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import get_settings
from app.phase3_store import list_alerts, list_watch_areas, mark_alert_delivery_result


def send_queued_email_alerts(limit: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    max_count = limit if limit is not None else settings.alert_delivery_rate_limit
    result: dict[str, Any] = {
        "configured": settings.alert_delivery_enabled,
        "attempted": 0,
        "sent": 0,
        "suppressed": 0,
        "failed": 0,
        "errors": [],
    }
    if not settings.alert_delivery_enabled:
        return result
    if not settings.smtp_host or not settings.smtp_from_email:
        result["configured"] = False
        result["errors"].append("SMTP_HOST and SMTP_FROM_EMAIL are required.")
        return result

    watch_areas = {watch_area["id"]: watch_area for watch_area in list_watch_areas()}
    queued_alerts = [
        alert
        for alert in list_alerts()
        if alert.get("status") == "queued" and alert.get("delivery_channel") == "email"
    ][:max_count]

    if not queued_alerts:
        return result

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            for alert in queued_alerts:
                result["attempted"] += 1
                watch_area = watch_areas.get(str(alert["watch_area_id"]))
                recipient = str((watch_area or {}).get("email_address") or "")
                if not watch_area or watch_area.get("unsubscribed_at") or not recipient:
                    mark_alert_delivery_result(alert["id"], status="suppressed")
                    result["suppressed"] += 1
                    continue
                message = _build_alert_message(
                    alert=alert,
                    watch_area=watch_area,
                    recipient=recipient,
                    sender=settings.smtp_from_email,
                    public_base_url=settings.public_base_url.rstrip("/"),
                )
                smtp.send_message(message)
                mark_alert_delivery_result(alert["id"], status="sent", sent_at=_now_iso())
                result["sent"] += 1
    except Exception as exc:  # pragma: no cover - exact SMTP failures vary by provider
        error = str(exc)
        result["errors"].append(error)
        for alert in queued_alerts[result["attempted"] :]:
            mark_alert_delivery_result(alert["id"], status="failed", error=error)
            result["failed"] += 1

    return result


def _build_alert_message(
    *,
    alert: dict[str, Any],
    watch_area: dict[str, Any],
    recipient: str,
    sender: str,
    public_base_url: str,
) -> EmailMessage:
    record_url = f"{public_base_url}/records/{alert['record_public_id']}"
    unsubscribe_url = (
        f"{public_base_url}/api/watch-areas/unsubscribe/"
        f"{watch_area['unsubscribe_token']}"
    )
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"Urbanization Tracker alert: {alert['record_title']}"
    message.set_content(
        "\n".join(
            [
                alert["summary"],
                "",
                f"Record: {record_url}",
                f"Watch area: {watch_area['name']}",
                "",
                f"Unsubscribe: {unsubscribe_url}",
            ]
        )
    )
    return message


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
