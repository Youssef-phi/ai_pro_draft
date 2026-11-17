"""Free, key-less research sources: DuckDuckGo HTML results, Wikipedia and Hacker News (Algolia).

Every result carries its real URL. Nothing here invents a URL: if a source fails,
it simply returns no results and the agents label their claims ASSUMPTION.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from tools.fetch import html_to_text, polite_get


def _result(title: str, url: str, snippet: str, source: str) -> dict:
    return {"title": html.unescape(title).strip()[:160], "url": url, "snippet": snippet.strip()[:400], "source": source}


def duckduckgo(query: str, n: int = 5) -> list[dict]:
    r = polite_get("https://html.duckduckgo.com/html/", params={"q": query})
    if r is None:
        return []
    results = []
    blocks = re.findall(r'(?s)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)', r.text)
    for href, title, rest in blocks:
        href = html.unescape(href)
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [""])[0])
        if not href.startswith("http") or "duckduckgo.com/y.js" in href:
            continue
        snippet = re.search(r'(?s)class="result__snippet"[^>]*>(.*?)</a>', rest)
        results.append(_result(html_to_text(title), href, html_to_text(snippet.group(1)) if snippet else "", "duckduckgo"))
        if len(results) >= n:
            break
    return results


def wikipedia(query: str, n: int = 2) -> list[dict]:
    r = polite_get("https://en.wikipedia.org/w/api.php",
                   params={"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json"})
    if r is None:
        return []
    try:
        hits = r.json()["query"]["search"]
    except (ValueError, KeyError):
        return []
    return [_result(h["title"], "https://en.wikipedia.org/wiki/" + quote(h["title"].replace(" ", "_")),
                    html_to_text(h.get("snippet", "")), "wikipedia") for h in hits]


def hacker_news(query: str, n: int = 3) -> list[dict]:
    r = polite_get("https://hn.algolia.com/api/v1/search", params={"query": query, "tags": "story", "hitsPerPage": n})
    if r is None:
        return []
    try:
        hits = r.json()["hits"]
    except (ValueError, KeyError):
        return []
    out = []
    for h in hits:
        url = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        note = f"Hacker News discussion, {h.get('points', 0)} points, {h.get('num_comments', 0)} comments."
        out.append(_result(h.get("title") or "", url, note, "hackernews"))
    return out
