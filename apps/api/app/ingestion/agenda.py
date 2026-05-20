from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.phase3_store import HUNTSVILLE_CENTER

PLANNING_ARCHIVE_URL = "https://www.huntsvilleal.gov/planningagendas/"
PLANNING_AGENCY = "City of Huntsville Planning Commission"


@dataclass(frozen=True)
class ParsedAgendaItem:
    title: str
    source_status: str
    normalized_status: str
    lot_count: int | None
    unit_count: int | None
    developer: str | None
    engineer: str | None
    location: str | None
    parse_confidence: str


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, str]:
    try:
        import fitz
    except ImportError:
        return "", "missing_pymupdf"

    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        text = "\n".join(page.get_text("text") for page in document)
    return text.strip(), "extracted"


def parse_agenda_items(
    text: str,
    *,
    source_document: dict[str, Any],
    checked_at: str,
) -> list[dict[str, Any]]:
    return [
        staged
        for item in _candidate_items(text)
        if (staged := _staged_record(item, source_document=source_document, checked_at=checked_at))
        is not None
    ]


def document_date_from_title(title: str, url: str) -> str | None:
    text = f"{title} {url}"
    month_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"[-\s]+(\d{1,2})[-,\s]+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        month = _month_number(month_match.group(1))
        return f"{month_match.group(3)}-{month:02d}-{int(month_match.group(2)):02d}"

    numeric_match = re.search(r"/(\d{4})/(\d{2})/", url)
    if numeric_match:
        return f"{numeric_match.group(1)}-{numeric_match.group(2)}-01"
    return None


def _candidate_items(text: str) -> list[ParsedAgendaItem]:
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^\d+\.\s+[A-Z0-9]", line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    items: list[ParsedAgendaItem] = []
    for block in blocks:
        parsed = _parse_block(block)
        if parsed:
            items.append(parsed)
    return items


def _parse_block(block: list[str]) -> ParsedAgendaItem | None:
    first_line = re.sub(r"^\d+\.\s+", "", block[0]).strip()
    if _section_header(first_line):
        return None
    body = " ".join(block[1:])
    statuses = _source_statuses(body)
    if not statuses:
        return None
    location = _field(body, "Located", stop_fields=("Developer", "Engineer", "Architect"))
    developer = _field(body, "Developer", stop_fields=("Engineer", "Architect", "Located"))
    engineer = _field(body, "Engineer", stop_fields=("Developer", "Architect", "Located"))
    lots = _count_for(body, "lot")
    units = _count_for(body, "unit")
    confidence = "medium" if location and (developer or engineer or lots or units) else "low"
    return ParsedAgendaItem(
        title=_title_case(first_line),
        source_status=" / ".join(statuses),
        normalized_status=_normalized_status(statuses),
        lot_count=lots,
        unit_count=units,
        developer=developer,
        engineer=engineer,
        location=location,
        parse_confidence=confidence,
    )


def _staged_record(
    item: ParsedAgendaItem,
    *,
    source_document: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    geometry = {"type": "Point", "coordinates": [HUNTSVILLE_CENTER[0], HUNTSVILLE_CENTER[1]]}
    document_date = source_document.get("document_date")
    staged_id = _stable_id("stage-agenda", source_document["id"], item.title, item.source_status)
    public_id = _stable_id("hsv-agenda", item.title, document_date or source_document["id"])
    description = _description(item)
    source_payload = {
        "source_document_id": source_document["id"],
        "source_document_title": source_document["title"],
        "document_date": document_date,
        "lot_count": item.lot_count,
        "unit_count": item.unit_count,
        "developer": item.developer,
        "engineer": item.engineer,
        "location": item.location,
        "parse_confidence": item.parse_confidence,
    }
    return {
        "id": staged_id,
        "title": item.title,
        "description": description,
        "development_type": "subdivision",
        "source_status": item.source_status,
        "normalized_status": item.normalized_status,
        "source_url": source_document["url"],
        "source_agency": PLANNING_AGENCY,
        "date_discovered": checked_at[:10],
        "review_status": "pending",
        "record_confidence": item.parse_confidence,
        "geometry_source": "Planning Commission agenda text; reviewer must match or draw geometry",
        "geometry_confidence": "low",
        "geometry": geometry,
        "source_payload": source_payload,
        "normalization_notes": (
            "PDF-derived candidate. Reviewer must confirm the agenda item, status, date, "
            "source document, duplicate risk, and geometry before publishing."
        ),
        "publish_record": {
            "public_id": public_id,
            "title": item.title,
            "description": description,
            "development_type": "subdivision",
            "status": item.normalized_status,
            "source_status": item.source_status,
            "source_url": source_document["url"],
            "source_agency": PLANNING_AGENCY,
            "date_discovered": checked_at[:10],
            "date_last_checked": checked_at[:10],
            "application_date": document_date,
            "approval_date": None,
            "permit_issue_date": None,
            "review_status": "published",
            "confidence_level": item.parse_confidence,
            "geometry_source": "Reviewer-approved Planning Commission agenda geometry",
            "geometry_confidence": "low",
            "geometry": geometry,
            "centroid": HUNTSVILLE_CENTER,
            "area_sq_m": None,
            "address": item.location,
            "parcel_ids": [],
            "source_fields": source_payload,
            "proximity_flags": [],
        },
    }


def _source_statuses(body: str) -> list[str]:
    matches = re.findall(
        r"\b(Boundary Plat|Repreliminary|Relayout|Layout|Preliminary|Final)\b",
        body,
        flags=re.IGNORECASE,
    )
    statuses: list[str] = []
    for match in matches:
        normalized = _title_case(match)
        if normalized not in statuses:
            statuses.append(normalized)
    return statuses


def _normalized_status(statuses: list[str]) -> str:
    lowered = {status.lower() for status in statuses}
    if "layout" in lowered or "relayout" in lowered:
        return "layout"
    if "preliminary" in lowered or "repreliminary" in lowered:
        return "preliminary"
    if "final" in lowered:
        return "final"
    return "proposed"


def _field(body: str, label: str, *, stop_fields: tuple[str, ...]) -> str | None:
    stop = "|".join(stop_fields)
    match = re.search(
        rf"{label}\s*:\s*(.*?)(?=\s+(?:{stop})\s*:|$)",
        body,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = re.split(
        r"\s+(?:I|II|III|IV|V)\.\s+|\s+Waiver\s*:|\s+Requested Rezoning\s*:|\s+Proposed Zoning\s*:",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .;")
    return value or None


def _count_for(body: str, noun: str) -> int | None:
    match = re.search(rf"\(\s*(\d+)\s+{noun}s?\s*\)", body, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _description(item: ParsedAgendaItem) -> str:
    count_bits = []
    if item.lot_count:
        count_bits.append(f"{item.lot_count} lots")
    if item.unit_count:
        count_bits.append(f"{item.unit_count} units")
    count_text = f" with {', '.join(count_bits)}" if count_bits else ""
    location_text = f" Location text: {item.location}." if item.location else ""
    return (
        "Planning Commission agenda candidate for "
        f"{item.source_status.lower()}{count_text}.{location_text}"
    )


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _section_header(value: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    return normalized in {
        "zoning",
        "location character and extent",
        "apartments subdivision presented for final",
        "apartments subdivisions presented for final",
        "subdivision name changes",
        "invocation extension of bonds",
    }


def _title_case(value: str) -> str:
    small_words = {"at", "and", "of", "the", "in", "on"}
    words = []
    for index, word in enumerate(value.lower().split()):
        words.append(word if index and word in small_words else word.capitalize())
    return " ".join(words)


def _month_number(month: str) -> int:
    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    return months.index(month.lower()) + 1


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", str(parts[-2] if len(parts) > 1 else parts[0]).lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:64] or "agenda"
    return f"{prefix}-{slug}-{digest}"
