from datetime import datetime, timedelta

from iris.agent.guardrails import Guardrail
from iris.agent.loop import AgentLoop
from iris.agent.tools import ToolRegistry
from iris.application.usage import compact, cost_usd
from iris.dataset.usage_ledger import SQLiteUsageLedger
from iris.domain.models import LLMResponse, Usage


class FakeLLM:
    def __init__(self, model):
        self.model = model

    def generate(self, system, messages, tools, on_text=None):
        return LLMResponse("Oi!", [], Usage(input_tokens=1200, output_tokens=80))


class NoKnowledge:
    def search(self, query, limit=5):
        return []


class NoRecorder:
    def record(self, interaction):
        pass


class AllowAll:
    def approve(self, call):
        return True


def run_loop(tmp_path, model):
    ledger = SQLiteUsageLedger(tmp_path / "usage.db", "Ana")
    loop = AgentLoop(FakeLLM(model), ToolRegistry([]), Guardrail(AllowAll()), NoKnowledge(), NoRecorder(), "system", ledger=ledger)
    loop.run("oi")
    loop.run("tudo bem?")
    return ledger


def test_local_model_records_tokens_without_cost(tmp_path):
    ledger = run_loop(tmp_path, "iris-1")
    totals = ledger.totals()
    assert (totals.calls, totals.input_tokens, totals.output_tokens, totals.cost) == (2, 2400, 160, 0.0)
    assert ledger.user == "Ana"


def test_claude_models_have_cost():
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, web_searches=2)
    assert round(cost_usd("claude-haiku-4-5-20251001", usage), 2) == round(1.0 + 0.5 + 0.02, 2)
    assert cost_usd("iris-1", usage) == 0.0


def test_periods_and_models(tmp_path):
    ledger = run_loop(tmp_path, "iris-1")
    labels = [label for label, _ in ledger.periods()]
    assert labels == ["today", "week", "month", "all"]
    assert ledger.totals(datetime.now() + timedelta(minutes=1)).calls == 0
    assert ledger.by_model()[0][0] == "iris-1"


def test_compact_numbers():
    assert (compact(950), compact(18_400), compact(2_500_000)) == ("950", "18,4k", "2,5M")
