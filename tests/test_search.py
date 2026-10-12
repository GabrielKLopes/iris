from types import SimpleNamespace

from iris.infrastructure.web.search import Hit, WebSearch, providers_from


class Failing:
    name = "failing"

    def hits(self, query, limit):
        raise RuntimeError("quota exceeded")


class Empty:
    name = "empty"

    def hits(self, query, limit):
        return []


class Working:
    name = "working"

    def hits(self, query, limit):
        return [Hit("Dólar hoje", "https://example.com/dolar", "Cotação do dia", "O dólar fechou em R$ 4,99.")]


def test_falls_back_to_the_next_provider_when_one_fails_or_finds_nothing():
    result = WebSearch([Failing(), Empty(), Working()], pages_to_read=0).search("dólar hoje")
    assert "Dólar hoje - https://example.com/dolar" in result
    assert "R$ 4,99" in result


def test_no_provider_finds_anything():
    assert WebSearch([Failing(), Empty()]).search("xyz") == "No results for 'xyz'"


def test_provider_order_prefers_keys_and_keeps_duckduckgo_as_last_resort():
    secrets = {"tavily": "t-key"}
    settings = SimpleNamespace(search_provider="auto", searxng_url="http://localhost:8080")
    names = [p.name for p in providers_from(settings, secrets.get, "tavily", "brave")]
    assert names == ["tavily", "searxng", "duckduckgo"]


def test_chosen_provider_goes_first():
    settings = SimpleNamespace(search_provider="searxng", searxng_url="http://localhost:8080")
    names = [p.name for p in providers_from(settings, {"tavily": "t"}.get, "tavily", "brave")]
    assert names[0] == "searxng" and names[-1] == "duckduckgo"
