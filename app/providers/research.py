"""Grounding: collect fresh facts + sources before any script is written.

Wikipedia needs no key and is always tried. Tavily (web search built for LLMs)
is used when TAVILY_API_KEY is set, which gives much fresher results for trends.
"""
from __future__ import annotations

import logging

import httpx

from .. import config

log = logging.getLogger("qreate.research")
UA = {"User-Agent": "Qreate/1.0 (Qoneqt CTRL FREAK hackathon; content pipeline)"}


def _tavily(query: str) -> list[dict]:
    r = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "max_results": 5,
            "include_answer": True,
            "search_depth": "basic",
        },
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    if data.get("answer"):
        out.append({"title": "Search summary", "url": "", "snippet": data["answer"]})
    for item in data.get("results", [])[:5]:
        out.append({"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")[:600]})
    return out


def _wikipedia(query: str, lang: str = "en") -> list[dict]:
    base = f"https://{lang}.wikipedia.org"
    r = httpx.get(
        f"{base}/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 3},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for hit in r.json().get("query", {}).get("search", [])[:3]:
        title = hit["title"]
        s = httpx.get(f"{base}/api/rest_v1/page/summary/{title.replace(' ', '_')}", headers=UA, timeout=15)
        if s.status_code != 200:
            continue
        js = s.json()
        extract = js.get("extract", "")
        if extract:
            out.append(
                {
                    "title": js.get("title", title),
                    "url": js.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "snippet": extract[:900],
                }
            )
    return out


def research(topic: str) -> list[dict]:
    """Return a list of {title, url, snippet}. Never raises: an empty list is valid."""
    if config.OFFLINE_MODE:
        return []
    notes: list[dict] = []
    if config.TAVILY_API_KEY:
        try:
            notes += _tavily(topic)
        except Exception as e:  # noqa: BLE001
            log.warning("Tavily failed: %s", e)
    try:
        notes += _wikipedia(topic)
    except Exception as e:  # noqa: BLE001
        log.warning("Wikipedia failed: %s", e)
    return notes[:8]


def trending_topics(geo: str = "IN") -> list[str]:
    """Live trending searches (Google Trends RSS). Falls back to evergreen ideas."""
    fallback = [
        "5 study habits backed by science",
        "How UPI changed payments in India",
        "Why ISRO missions cost so little",
        "The psychology of doomscrolling",
        "Budget travel hacks for students",
        "What AI agents can do in 2026",
    ]
    if config.OFFLINE_MODE:
        return fallback
    try:
        import xml.etree.ElementTree as ET

        r = httpx.get(f"https://trends.google.com/trending/rss?geo={geo}", headers=UA, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        titles = [i.findtext("title") for i in root.iter("item")]
        titles = [t for t in titles if t]
        return titles[:12] or fallback
    except Exception as e:  # noqa: BLE001
        log.info("Trends unavailable (%s); using fallback ideas", e)
        return fallback
