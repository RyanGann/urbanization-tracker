from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin


@dataclass(frozen=True)
class AgendaLink:
    title: str
    url: str


class _AgendaArchiveParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[AgendaLink] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current_href = urljoin(self.base_url, href)
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._current_href:
            return
        text = " ".join(part.strip() for part in self._current_text if part.strip())
        url = self._current_href
        self._current_href = None
        self._current_text = []
        lowered = f"{text} {url}".lower()
        if ".pdf" not in lowered or "agenda" not in lowered or "minutes" in lowered:
            return
        self.links.append(AgendaLink(title=_link_title(text, url), url=url))


def discover_agenda_links(
    html: str,
    *,
    base_url: str,
    limit: int | None = None,
) -> list[AgendaLink]:
    parser = _AgendaArchiveParser(base_url)
    parser.feed(html)
    deduped: dict[str, AgendaLink] = {}
    for link in parser.links:
        deduped.setdefault(link.url, link)
    links = list(deduped.values())
    return links if limit is None else links[:limit]


def _link_title(text: str, url: str) -> str:
    if text and text.strip().lower() not in {"download", "attached file"}:
        return text.strip()
    filename = unquote(url.rsplit("/", 1)[-1])
    filename = filename.rsplit(".", 1)[0]
    filename = filename.replace("-", " ")
    return filename or "Planning Commission agenda"
