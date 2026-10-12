from iris.domain.models import ToolCall, ToolResult
from iris.tui.previews import language_of, preview_for



def test_language_from_file_name():
    assert language_of("Projetos/loja/docker-compose.yml") == "yaml"
    assert language_of("C:\app\Dockerfile") == "dockerfile"
    assert language_of("script.ps1") == "powershell"
    assert language_of("notes") == "text"


def test_write_file_shows_the_content_expanded():
    call = ToolCall("1", "write_file", {"path": "loja/docker-compose.yml", "content": "services:\n  db:\n    image: postgres:17\n"})
    preview = preview_for(call, ToolResult("1", "Wrote 3 lines"), "en")
    assert preview is not None and not preview.collapsed and preview.title == "3 lines"


def test_long_files_are_trimmed():
    from iris.tui.previews import fence

    body = fence("\n".join(f"line {i}" for i in range(40)), "text", "en")
    assert "line 17" in body and "line 18" not in body and "22 more lines" in body


def test_web_search_lists_sources():
    content = "Dólar hoje - https://wise.com/br\nCotação do dia\n\nUOL Economia - https://economia.uol.com.br\nDólar"
    preview = preview_for(ToolCall("2", "web_search", {"query": "dólar"}), ToolResult("2", content), "pt")
    assert preview is not None and preview.title == "2 fontes encontradas"


def test_errors_and_pending_commands_have_no_preview():
    assert preview_for(ToolCall("3", "write_file", {"path": "x"}), ToolResult("3", "Failed", is_error=True), "en") is None
    pending = ToolResult("4", "Not run yet. Ask the user if you may run: rm x. Confirmation code: ab12")
    assert preview_for(ToolCall("4", "run_command", {"command": "rm x"}), pending, "en") is None
