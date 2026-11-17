"""Free page fetch and text extraction. Respects robots.txt and waits between requests to a host."""
from __future__ import annotations

import html
import re
import threading
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

USER_AGENT = "VentureBoardResearchBot/0.1 (open-source hackathon project; respects robots.txt)"
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_last_hit: dict[str, float] = {}
_lock = threading.Lock()


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True,
                        headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})


def allowed(url: str) -> bool:
    """True if robots.txt lets us fetch this URL (unknown or unreachable robots.txt counts as allowed)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = f"{parts.scheme}://{parts.netloc}"
    with _lock:
        if host not in _robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                with _client() as client:
                    r = client.get(host + "/robots.txt")
                parser.parse(r.text.splitlines() if r.status_code == 200 else [])
                _robots[host] = parser
            except httpx.HTTPError:
                _robots[host] = None
        parser = _robots[host]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


def polite_get(url: str, params: dict | None = None, min_gap: float = 1.0) -> httpx.Response | None:
    """GET with a robots check and at least `min_gap` seconds between hits to the same host."""
    if not allowed(url):
        return None
    host = urlsplit(url).netloc
    with _lock:
        wait = _last_hit.get(host, 0.0) + min_gap - time.monotonic()
        _last_hit[host] = time.monotonic() + max(wait, 0.0)
    if wait > 0:
        time.sleep(wait)
    try:
        with _client() as client:
            r = client.get(url, params=params)
        return r if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form)\b.*?</\1>", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", markup)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_text(url: str, max_chars: int = 1500) -> str:
    """Readable text of a page, or '' if it cannot be fetched. Never raises."""
    r = polite_get(url)
    if r is None or "html" not in r.headers.get("content-type", "html"):
        return ""
    return html_to_text(r.text)[:max_chars]
