import pytest

from iris.agent.tools import ToolRegistry
from fakes import EchoTool


def test_registry_rejects_duplicate_tool():
    registry = ToolRegistry([EchoTool()])
    with pytest.raises(ValueError):
        registry.add(EchoTool())


def test_registry_gets_by_name():
    registry = ToolRegistry([EchoTool()])
    assert registry.get("echo").name == "echo"
    assert registry.get("missing") is None
