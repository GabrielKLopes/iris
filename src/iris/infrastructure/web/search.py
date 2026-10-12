from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Protocol

import httpx

from iris.infrastructure.web.pages import fetch_text


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    content: str = ""


class Provider(Protocol):
    name: str

    def hits(self, query: str, limit: int) -> list[Hit]: ...


class DuckDuckGo:
    name = "duckduckgo"

    def __init__(self, region: str = "br-pt"):
        self.region = region

    def hits(self, query: str, limit: int) -> list[Hit]:
        from ddgs import DDGS

        return [Hit(h["title"], h["href"], h["body"]) for h in DDGS().text(query, region=self.region, max_results=limit) or []]


class Tavily:
    name = "tavily"

    def __init__(self, api_key: str, timeout: float = 8.0):
        self.api_key = api_key
        self.timeout = timeout

    def hits(self, query: str, limit: int) -> list[Hit]:
        response = httpx.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"query": query, "max_results": limit, "search_depth": "basic", "include_answer": False},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return [Hit(r.get("title", ""), r.get("url", ""), r.get("content", ""), r.get("content", "")) for r in response.json().get("results", [])]


class Brave:
    name = "brave"

    def __init__(self, api_key: str, timeout: float = 8.0):
        self.api_key = api_key
        self.timeout = timeout

    def hits(self, query: str, limit: int) -> list[Hit]:
        response = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit, "country": "BR", "search_lang": "pt-br"},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = response.json().get("web", {}).get("results", [])
        return [Hit(r.get("title", ""), r.get("url", ""), r.get("description", "")) for r in results]


class Searxng:
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def hits(self, query: str, limit: int) -> list[Hit]:
        response = httpx.get(f"{self.base_url}/search", params={"q": query, "format": "json", "language": "pt-BR"}, timeout=self.timeout)
        response.raise_for_status()
        return [Hit(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in response.json().get("results", [])[:limit]]


class WebSearch:
    def __init__(self, providers: list[Provider], results: int = 5, pages_to_read: int = 2, excerpt: int = 1200, timeout: float = 2.5):
        self.providers = providers
        self.results = results
        self.pages_to_read = pages_to_read
        self.excerpt = excerpt
        self.timeout = timeout

    def search(self, query: str) -> str:
        hits: list[Hit] = []
        source = ""
        for provider in self.providers:
            try:
                hits = provider.hits(query, self.results)
            except Exception as exc:
                logging.warning("Search provider %s failed: %s", provider.name, exc)
                continue
            if hits:
                source = provider.name
                break
        if not hits:
            return f"No results for '{query}'"
        logging.info("Web search via %s: %s", source, query)
        missing = [h.url for h in hits[: self.pages_to_read] if not h.content]
        excerpts = self._read_pages(missing) if missing else {}
        lines = []
        for hit in hits:
            lines.append(f"{hit.title} - {hit.url}\n{hit.snippet}")
            content = hit.content if hit.content and hit.content != hit.snippet else excerpts.get(hit.url, "")
            if content:
                lines.append(f"Page excerpt: {' '.join(content.split())[: self.excerpt]}")
        return "\n\n".join(lines)

    def _read_pages(self, urls: list[str]) -> dict[str, str]:
        def read(url: str) -> tuple[str, str]:
            try:
                return url, fetch_text(url, self.timeout)[1]
            except Exception as exc:
                logging.debug("Could not read %s: %s", url, exc)
                return url, ""

        pool = ThreadPoolExecutor(len(urls))
        futures = [pool.submit(read, url) for url in urls]
        done, _ = wait(futures, timeout=self.timeout + 0.5)
        pool.shutdown(wait=False, cancel_futures=True)
        return dict(f.result() for f in done)


def providers_from(settings, get_secret, tavily_key: str, brave_key: str) -> list[Provider]:
    wanted = settings.search_provider
    available: dict[str, Provider] = {}
    if key := get_secret(tavily_key):
        available["tavily"] = Tavily(key)
    if key := get_secret(brave_key):
        available["brave"] = Brave(key)
    if settings.searxng_url:
        available["searxng"] = Searxng(settings.searxng_url)
    available["duckduckgo"] = DuckDuckGo()
    order = ["tavily", "brave", "searxng", "duckduckgo"]
    if wanted in available:
        order.remove(wanted)
        order.insert(0, wanted)
    return [available[name] for name in order if name in available]
