from app.ingestion.agenda import parse_agenda_items
from app.ingestion.connectors.agenda import discover_agenda_links


def test_discovers_agenda_pdf_links_without_minutes() -> None:
    html = """
    <a href="/wp-content/uploads/2026/04/sample-agenda.pdf">Planning Commission Agenda</a>
    <a href="/wp-content/uploads/2026/04/sample-minutes.pdf">Download Minutes</a>
    """

    links = discover_agenda_links(html, base_url="https://www.huntsvilleal.gov/planningagendas/")

    assert len(links) == 1
    assert links[0].url == "https://www.huntsvilleal.gov/wp-content/uploads/2026/04/sample-agenda.pdf"


def test_parses_agenda_items_into_pending_staged_records() -> None:
    source_document = {
        "id": "agenda-test",
        "title": "Planning Commission Agenda - Test",
        "url": "https://example.test/agenda.pdf",
        "document_date": "2026-04-28",
    }
    text = """
    PLANNING COMMISSION AGENDA
    1. SAMPLE RIDGE PHASE 2
    Layout (24 lots) Developer: Example Development LLC
    Engineer: Sample Engineering
    Located: Southwest City; west of Example Road.
    2. ZONING
    a) SAMPLE REZONING
    Proposed Zoning: Highway Business
    """

    records = parse_agenda_items(
        text,
        source_document=source_document,
        checked_at="2026-05-20T12:00:00Z",
    )

    assert len(records) == 1
    record = records[0]
    assert record["title"] == "Sample Ridge Phase 2"
    assert record["normalized_status"] == "layout"
    assert record["review_status"] == "pending"
    assert record["geometry_confidence"] == "low"
    assert record["source_payload"]["lot_count"] == 24
    assert record["publish_record"]["source_url"] == "https://example.test/agenda.pdf"
