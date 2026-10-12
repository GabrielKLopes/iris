import re

import httpx
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"}
BOT_HEADERS = {"User-Agent": "IrisAssistant/1.0 (+https://github.com/GabrielKLopes/iris)"}
MARKDOWN_ESCAPE = re.compile(r"\\([_*\[\]#`<>|-])")
FOOTNOTES = re.compile(r"<sup>.*?</sup>|\[editar( \| editar código)?\]|\[edit\]", re.IGNORECASE)
TAGS = re.compile(r"</?(sup|sub|span|div|small|abbr)[^>]*>", re.IGNORECASE)


def fetch_html(url: str, timeout: float = 6.0) -> str:
    response = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
    if response.status_code == 403:
        response = httpx.get(url, headers=BOT_HEADERS, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def page_text(html: str) -> tuple[str, str]:
    text = trafilatura.extract(
        html, output_format="markdown", include_formatting=True, include_comments=False, include_tables=True, favor_recall=True
    ) or ""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata and metadata.title else ""
    text = TAGS.sub("", FOOTNOTES.sub("", MARKDOWN_ESCAPE.sub(r"\1", text)))
    return title, re.sub(r"\n{3,}", "\n\n", text)


def fetch_text(url: str, timeout: float = 6.0) -> tuple[str, str]:
    return page_text(fetch_html(url, timeout))
