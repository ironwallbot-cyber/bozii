"""Search provider adapters.

Bozii never fabricates search results: if the configured provider cannot be
reached, the tool returns an explicit configuration error.
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from bozii.config import get_settings

_FETCH_TIMEOUT = 20.0


class SearchResult:
    __slots__ = ("title", "url", "snippet")

    def __init__(self, title: str, url: str, snippet: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current: list[tuple[str, str]] = []
        self.results: list[dict] = []
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._capture = "title"
            self._buf = []
            self._link = attr.get("href") or ""
        elif tag in {"a", "td", "div", "span"} and "result__snippet" in classes:
            self._capture = "snippet"
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._capture:
            return
        text = html.unescape(" ".join("".join(self._buf).split()))
        if self._capture == "title":
            self.current_title = text
            self.current_link = getattr(self, "_link", "")
            self._pending = {"title": text, "url": self.current_link, "snippet": ""}
            self.results.append(self._pending)
        elif self._capture == "snippet" and getattr(self, "_pending", None):
            self._pending["snippet"] = text
        self._capture = None
        self._buf = []


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)

    @property
    def text(self) -> str:
        joined = " ".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", joined)).strip()


def html_to_text(markup: str) -> tuple[str, list[str]]:
    extractor = _TextExtractor()
    try:
        extractor.feed(markup)
    except Exception:
        return re.sub(r"<[^>]+>", " ", markup), []
    return extractor.text, extractor._hrefs


def decode_ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        if "uddg" in query:
            return unquote(query["uddg"][0])
    return href


async def search_duckduckgo(query: str, limit: int) -> list[SearchResult]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Bozii/0.1; +https://github.com/bozii/bozii)"}
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise RuntimeError(f"Search provider answered HTTP {resp.status_code}")
    parser = _LinkParser()
    parser.feed(resp.text)
    out: list[SearchResult] = []
    for item in parser.results:
        link = decode_ddg_url(item.get("url") or "")
        if not link or link.startswith("/"):
            continue
        out.append(SearchResult(item.get("title") or link, link, item.get("snippet") or ""))
        if len(out) >= limit:
            break
    if not out:
        # Fall back to the lite endpoint before giving up.
        lite = "https://lite.duckduckgo.com/lite/"
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True, headers=headers) as client:
            resp2 = await client.post(lite, data={"q": query})
        text, _ = html_to_text(resp2.text)
        for match in re.finditer(r"https?://[^\s\"'<>]+", resp2.text):
            candidate = decode_ddg_url(match.group(0))
            if "duckduckgo.com" in candidate:
                continue
            out.append(SearchResult(candidate, candidate, ""))
            if len(out) >= limit:
                break
    if not out:
        raise RuntimeError("The search provider returned no results (possible rate limit or block)")
    return out


async def search_searxng(query: str, limit: int) -> list[SearchResult]:
    settings = get_settings()
    base = settings.searxng_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(f"{base}/search", params={"q": query, "format": "json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"SearXNG answered HTTP {resp.status_code}")
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("SearXNG did not return JSON (is format=json enabled?)") from exc
    out = [
        SearchResult(r.get("title") or "", r.get("url") or "", r.get("content") or "")
        for r in (data.get("results") or [])[:limit]
    ]
    if not out:
        raise RuntimeError("SearXNG returned no results")
    return out


async def web_search(query: str, limit: int = 8) -> tuple[list[SearchResult], str]:
    """Run a search through the configured provider. Returns (results, provider)."""
    settings = get_settings()
    provider = (settings.search_provider or "duckduckgo").lower()
    if provider == "searxng" and not settings.searxng_url:
        raise RuntimeError(
            "SEARCH_PROVIDER=searxng but SEARXNG_URL is not set. "
            "Point it at a SearXNG instance or use SEARCH_PROVIDER=duckduckgo."
        )
    if provider == "searxng":
        return await search_searxng(query, limit), "searxng"
    return await search_duckduckgo(query, limit), "duckduckgo"


__all__ = ["SearchResult", "html_to_text", "web_search"]
