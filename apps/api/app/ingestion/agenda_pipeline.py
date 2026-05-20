from __future__ import annotations

import hashlib
import re
import ssl
import subprocess
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import certifi
import httpx

from app.ingestion.agenda import (
    PLANNING_AGENCY,
    PLANNING_ARCHIVE_URL,
    document_date_from_title,
    extract_pdf_text,
    parse_agenda_items,
)
from app.ingestion.artifacts import ensure_data_dirs, iso_now, read_json, write_json
from app.ingestion.connectors.agenda import discover_agenda_links
from app.phase3_store import build_duplicate_candidates, replace_agenda_artifacts

FALLBACK_AGENDA_LINKS = [
    (
        "Planning Commission Agenda - April 28, 2026",
        "https://www.huntsvilleal.gov/wp-content/uploads/2026/04/"
        "Planning-Commission-Agenda-April-20206.pdf",
    ),
    (
        "Planning Commission Agenda - March 24, 2026",
        "https://www.huntsvilleal.gov/wp-content/uploads/2026/03/"
        "Planning-Commission-Agenda-March-2026-1.pdf",
    ),
    (
        "Planning Commission Agenda - February 24, 2026",
        "https://www.huntsvilleal.gov/wp-content/uploads/2026/02/"
        "Planning-Commission-Agenda-Feb-2026-2.pdf",
    ),
    (
        "Planning Commission Agenda - January 27, 2026",
        "https://www.huntsvilleal.gov/wp-content/uploads/2026/01/"
        "Planning-Commission-Agenda-January-2026-2.pdf",
    ),
]


def ingest_huntsville_agendas(
    *,
    data_dir: Path,
    document_limit: int = 3,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    ensure_data_dirs(data_dir)
    checked_at = iso_now()
    owned_client = client is None
    client = client or httpx.Client(
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; UrbanizationTracker/0.1; "
                "+https://github.com/local/urbanization-tracker)"
            )
        },
    )
    source_documents: list[dict[str, Any]] = []
    staged_records: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        archive_html, discovery_method = _fetch_archive_html(client)
        write_json(
            data_dir / "raw" / "planning_agendas" / "archive-page.json",
            {
                "url": PLANNING_ARCHIVE_URL,
                "fetched_at": checked_at,
                "html": archive_html,
                "discovery_method": discovery_method,
            },
        )
        if archive_html:
            links = discover_agenda_links(
                archive_html,
                base_url=PLANNING_ARCHIVE_URL,
                limit=document_limit,
            )
        else:
            from app.ingestion.connectors.agenda import AgendaLink

            links = [
                AgendaLink(title=title, url=url)
                for title, url in FALLBACK_AGENDA_LINKS[:document_limit]
            ]

        for link in links:
            try:
                document, records = _fetch_and_parse_document(
                    client=client,
                    data_dir=data_dir,
                    title=link.title,
                    url=link.url,
                    checked_at=checked_at,
                )
                source_documents.append(document)
                staged_records.extend(records)
            except Exception as exc:
                errors.append(f"{link.url}: {exc}")

        staged_records = _dedupe(staged_records, key="id")
        published_records = _published_records(data_dir)
        duplicate_candidates = build_duplicate_candidates(staged_records, published_records)
        health = {
            "key": "huntsville_planning_agendas",
            "name": "Huntsville Planning Commission Agendas",
            "source_url": PLANNING_ARCHIVE_URL,
            "status": "healthy" if not errors else "degraded",
            "checked_at": checked_at,
            "records_seen": sum(document["parsed_item_count"] for document in source_documents),
            "records_created": len(staged_records),
            "documents_seen": len(source_documents),
            "error_count": len(errors),
            "validation_errors": errors,
            "metadata": {
                "document_limit": document_limit,
                "agency": PLANNING_AGENCY,
                "discovery_method": discovery_method,
            },
        }
        replace_agenda_artifacts(
            source_documents=source_documents,
            staged_records=staged_records,
            duplicate_candidates=duplicate_candidates,
            health=health,
        )
        return health
    finally:
        if owned_client:
            client.close()


def _fetch_and_parse_document(
    *,
    client: httpx.Client,
    data_dir: Path,
    title: str,
    url: str,
    checked_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pdf_bytes, content_type = _fetch_pdf_bytes(client, url)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    document_id = f"agenda-{digest[:12]}"
    raw_path = data_dir / "raw" / "planning_agendas" / f"{document_id}.pdf"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(pdf_bytes)

    extracted_text, extraction_status = extract_pdf_text(pdf_bytes)
    text_path = data_dir / "processed" / "source_documents" / f"{document_id}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(extracted_text, encoding="utf-8")

    source_document = {
        "id": document_id,
        "title": title or "Planning Commission agenda",
        "url": url,
        "document_date": document_date_from_title(title, url),
        "fetched_at": checked_at,
        "sha256": digest,
        "content_type": content_type,
        "storage_uri": str(raw_path),
        "extracted_text_uri": str(text_path),
        "extraction_status": extraction_status,
        "parsed_item_count": 0,
        "text_excerpt": _excerpt(extracted_text),
    }
    staged_records = parse_agenda_items(
        extracted_text,
        source_document=source_document,
        checked_at=checked_at,
    )
    source_document["parsed_item_count"] = len(staged_records)
    return source_document, staged_records


def _published_records(data_dir: Path) -> list[dict[str, Any]]:
    records = read_json(data_dir / "processed" / "development_records.json", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _fetch_archive_html(client: httpx.Client) -> tuple[str, str]:
    try:
        response = client.get(PLANNING_ARCHIVE_URL)
        response.raise_for_status()
        return response.text, "httpx_archive"
    except httpx.HTTPError:
        curl_html = _curl_text(PLANNING_ARCHIVE_URL)
        if curl_html:
            return curl_html, "curl_archive"
        return "", "curated_fallback"


def _fetch_pdf_bytes(client: httpx.Client, url: str) -> tuple[bytes, str]:
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "application/pdf")
    except httpx.HTTPError:
        return _urllib_bytes(url)


def _urllib_bytes(url: str) -> tuple[bytes, str]:
    context = ssl.create_default_context(cafile=certifi.where())
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30, context=context) as response:
            content_type = response.headers.get("content-type", "application/pdf")
            return response.read(), content_type
    except Exception:
        curl_bytes = _curl_bytes(url)
        if curl_bytes:
            return curl_bytes, "application/pdf"
        raise


def _curl_text(url: str) -> str | None:
    result = _run_curl(url)
    if result is None:
        return None
    return result.decode("utf-8", errors="replace")


def _curl_bytes(url: str) -> bytes | None:
    return _run_curl(url)


def _run_curl(url: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["curl", "-fsSL", url],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout


def _dedupe(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped[str(record[key])] = record
    return list(deduped.values())


def _excerpt(text: str) -> str | None:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return None
    return clean[:700]
