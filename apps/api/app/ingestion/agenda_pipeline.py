from __future__ import annotations

import hashlib
import re
import ssl
import subprocess
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID

import certifi
import httpx

from app.config import get_settings
from app.ingestion.agenda import (
    PLANNING_AGENCY,
    PLANNING_ARCHIVE_URL,
    document_date_from_title,
    extract_pdf_text,
    parse_agenda_items,
)
from app.ingestion.artifact_manifest import public_source_url
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import ArtifactError
from app.ingestion.artifacts import (
    ensure_data_dirs,
    iso_now,
    read_json,
    record_artifact,
    write_staged_bytes,
    write_staged_json,
)
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
    if get_settings().hosted_ingestion_enabled and not get_settings().artifact_durability_required:
        raise ArtifactError("artifact_configuration")
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
    required_references: list[UUID] = []
    artifact_pending = False
    run_id = checked_at.replace(":", "").replace("+", "Z")
    artifact_service: ArtifactService | None = None
    if get_settings().artifact_durability_required:
        from app.db import SessionLocal

        artifact_service = ArtifactService(
            get_settings().model_copy(update={"ingestion_data_dir": data_dir}), SessionLocal
        )

    try:
        archive_html, discovery_method = _fetch_archive_html(client)
        archive_path = data_dir / "raw" / "planning_agendas" / "archive-page.json"
        write_staged_json(
            data_dir,
            archive_path,
            {
                "url": PLANNING_ARCHIVE_URL,
                "fetched_at": checked_at,
                "html": archive_html,
                "discovery_method": discovery_method,
            },
        )
        record_artifact(
            data_dir=data_dir,
            path=archive_path,
            artifact_type="archive_page",
            source_key="huntsville_planning_agendas",
            run_id=run_id,
            source_url=PLANNING_ARCHIVE_URL,
            content_type="application/json",
        )
        if artifact_service is not None:
            try:
                archive_reference = artifact_service.upload_file(
                    path=archive_path,
                    source_key="huntsville_planning_agendas",
                    run_id=run_id,
                    artifact_type="archive_page",
                    logical_key="archive",
                    required=False,
                    content_type="application/json",
                    source_url=PLANNING_ARCHIVE_URL,
                )
                artifact_service.cleanup_verified(archive_reference, archive_path)
            except ArtifactError:
                # Archive discovery is optional provenance; exact PDF/text pairs
                # still determine whether the parsed revision may publish.
                pass
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
                document, records, references = _fetch_and_parse_document(
                    client=client,
                    data_dir=data_dir,
                    title=link.title,
                    url=link.url,
                    checked_at=checked_at,
                    artifact_service=artifact_service,
                )
                source_documents.append(document)
                staged_records.extend(records)
                required_references.extend(references)
            except ArtifactError as exc:
                artifact_pending = True
                errors.append(exc.code)
            except Exception as exc:
                if artifact_service is not None:
                    artifact_pending = True
                    errors.append("agenda_source_error")
                else:
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
        if artifact_pending:
            return health
        replace_agenda_artifacts(
            source_documents=source_documents,
            staged_records=staged_records,
            duplicate_candidates=duplicate_candidates,
            health=health,
            run_id=run_id if artifact_service is not None else None,
            artifact_sink_id=artifact_service.sink_id if artifact_service is not None else None,
            required_reference_ids=tuple(required_references),
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
    artifact_service: ArtifactService | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], tuple[UUID, ...]]:
    pdf_bytes, content_type = _fetch_pdf_bytes(client, url)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    document_id = f"agenda-{digest[:12]}"
    run_id = checked_at.replace(":", "").replace("+", "Z")
    raw_path = data_dir / "raw" / "planning_agendas" / f"{document_id}.pdf"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    write_staged_bytes(data_dir, raw_path, pdf_bytes)
    raw_artifact = record_artifact(
        data_dir=data_dir,
        path=raw_path,
        artifact_type="source_pdf",
        source_key="huntsville_planning_agendas",
        run_id=run_id,
        source_url=url,
        content_type=content_type,
    )
    pdf_reference = (
        artifact_service.upload_file(
            path=raw_path,
            source_key="huntsville_planning_agendas",
            run_id=run_id,
            artifact_type="source_pdf",
            logical_key=document_id,
            required=True,
            content_type=content_type,
            source_url=url,
        )
        if artifact_service is not None else None
    )

    extracted_text, extraction_status = extract_pdf_text(pdf_bytes)
    text_path = data_dir / "processed" / "source_documents" / f"{document_id}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    write_staged_bytes(data_dir, text_path, extracted_text.encode("utf-8"))
    text_artifact = record_artifact(
        data_dir=data_dir,
        path=text_path,
        artifact_type="extracted_text",
        source_key="huntsville_planning_agendas",
        run_id=run_id,
        source_url=url,
        content_type="text/plain; charset=utf-8",
        metadata={"source_document_id": document_id},
    )
    text_reference = (
        artifact_service.upload_file(
            path=text_path,
            source_key="huntsville_planning_agendas",
            run_id=run_id,
            artifact_type="extracted_text",
            logical_key=f"{document_id}:extract-v1",
            required=True,
            content_type="text/plain; charset=utf-8",
            source_url=url,
            parent_reference_id=pdf_reference,
        )
        if artifact_service is not None else None
    )
    if artifact_service is not None and pdf_reference is not None and text_reference is not None:
        artifact_service.cleanup_verified(pdf_reference, raw_path)
        artifact_service.cleanup_verified(text_reference, text_path)

    source_document = {
        "id": document_id,
        "title": title or "Planning Commission agenda",
        "url": public_source_url(url) or "",
        "document_date": document_date_from_title(title, url),
        "fetched_at": checked_at,
        "sha256": digest,
        "content_type": content_type,
        "storage_uri": raw_artifact["storage_uri"],
        "extracted_text_uri": text_artifact["storage_uri"],
        "pdf_reference_id": str(pdf_reference) if pdf_reference is not None else None,
        "text_reference_id": str(text_reference) if text_reference is not None else None,
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
    references = tuple(ref for ref in (pdf_reference, text_reference) if ref is not None)
    return source_document, staged_records, references


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
