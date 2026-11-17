"""Research tools. research() returns an evidence pack: a list of {title, url, snippet, source}."""
from __future__ import annotations

import re

from tools import fetch, search

_STOP = set("a an and are as at be but by for from has have i in is it its my of on or our so that the their "
            "they this to want we who will with you your app tool product digital online build make create "
            "help helps people users small simple new".split())


def keywords(text: str, n: int = 5) -> str:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower()) if w not in _STOP]
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return " ".join(out[:n])


def normalize_url(url: str) -> str:
    return (url or "").strip().split("#")[0].rstrip("/")


def research(queries: list[str], max_results: int = 10, read_pages: int = 3) -> list[dict]:
    """Search the free sources for each query and read the top pages. Never raises; may return []."""
    pack, seen = [], set()

    def add(items: list[dict]) -> None:
        for item in items:
            key = normalize_url(item["url"])
            if key and key not in seen and len(pack) < max_results:
                seen.add(key)
                pack.append(item)

    for i, query in enumerate([q for q in queries if q.strip()][:3]):
        add(search.duckduckgo(query, 4))
        add(search.hacker_news(keywords(query, 3), 2))
        if i == 0:
            add(search.wikipedia(keywords(query, 4), 2))
    for item in [p for p in pack if p["source"] == "duckduckgo"][:read_pages]:
        excerpt = fetch.fetch_text(item["url"], 1200)
        if excerpt:
            item["excerpt"] = excerpt
    return pack
