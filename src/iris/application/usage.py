from __future__ import annotations

from iris.domain.models import Usage

PRICES_PER_MILLION = {
    "haiku": (1.0, 5.0, 0.10, 1.25),
    "sonnet": (3.0, 15.0, 0.30, 3.75),
    "opus": (5.0, 25.0, 0.50, 6.25),
}
WEB_SEARCH_PRICE = 0.01


def cost_usd(model: str, usage: Usage) -> float:
    family = next((name for name in PRICES_PER_MILLION if name in model.lower()), None)
    if family is None:
        return 0.0
    price_in, price_out, price_cache_read, price_cache_write = PRICES_PER_MILLION[family]
    return (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + usage.cache_read_tokens * price_cache_read
        + usage.cache_write_tokens * price_cache_write
    ) / 1_000_000 + usage.web_searches * WEB_SEARCH_PRICE


def compact(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M".replace(".", ",")
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k".replace(".", ",")
    return str(tokens)
