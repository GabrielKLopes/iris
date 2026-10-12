from iris.agent.tools.files import DeleteFilesTool, ListFolderTool
from iris.infrastructure.windows.files import LocalFiles


def build(tmp_path):
    files = LocalFiles(roots=[tmp_path], home=tmp_path)
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "setup.exe").write_bytes(b"x" * 10)
    return files


def test_lists_known_folder_and_blocks_paths_outside_roots(tmp_path):
    files = build(tmp_path)
    assert "setup.exe" in ListFolderTool(files).run({"folder": "Downloads"})
    assert ListFolderTool(files).run({"folder": "C:/Windows"}).startswith("Failed")


def test_delete_needs_a_later_turn_and_the_code(tmp_path, monkeypatch):
    files = build(tmp_path)
    deleted = []
    monkeypatch.setattr(files, "delete", lambda paths: deleted.extend(paths) or "Sent")
    turn = {"value": 1}
    tool = DeleteFilesTool(files, lambda: turn["value"])
    target = str(tmp_path / "Downloads" / "setup.exe")

    first = tool.run({"paths": [target]})
    code = first.rsplit(" ", 1)[-1]
    assert "Nothing deleted" in first and not deleted
    assert "not answered" in tool.run({"paths": [target], "confirmation": code})
    turn["value"] = 2
    assert tool.run({"paths": [target], "confirmation": "wrong"}).startswith("Invalid")
    first = tool.run({"paths": [target]})
    turn["value"] = 3
    assert tool.run({"paths": [target], "confirmation": first.rsplit(" ", 1)[-1]}) == "Sent"
    assert len(deleted) == 1
