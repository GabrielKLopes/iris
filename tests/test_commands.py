from iris.agent.tools.commands import RunCommandTool, is_read_only


def test_read_only_detection():
    assert is_read_only("git status")
    assert is_read_only("docker ps | Select-Object -First 3")
    assert is_read_only("Get-Process | Sort-Object CPU")
    assert not is_read_only("docker rm -f api")
    assert not is_read_only("git status; Remove-Item x")
    assert not is_read_only("Get-Process | Stop-Process")
    assert not is_read_only("git push")


def test_changing_commands_need_a_later_turn():
    ran = []
    turn = {"value": 1}
    tool = RunCommandTool(lambda: turn["value"], runner=lambda command, cwd: ran.append(command) or "Exit code 0")

    assert tool.run({"command": "git status"}) == "Exit code 0"
    first = tool.run({"command": "docker restart api"})
    code = first.rsplit(" ", 1)[-1]
    assert "Not run yet" in first and ran == ["git status"]
    assert "not answered" in tool.run({"command": "docker restart api", "confirmation": code})
    turn["value"] = 2
    assert tool.run({"command": "docker restart api", "confirmation": code}) == "Exit code 0"
    assert ran == ["git status", "docker restart api"]


def test_leading_cd_becomes_working_folder(tmp_path):
    ran = []
    tool = RunCommandTool(lambda: 1, runner=lambda command, cwd: ran.append((command, cwd)) or "Exit code 0")
    assert tool.run({"command": f"cd {tmp_path} && git branch --show-current"}) == "Exit code 0"
    assert ran == [("git branch --show-current", tmp_path)]
