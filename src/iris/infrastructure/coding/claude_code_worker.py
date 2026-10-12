import asyncio
import logging
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, create_sdk_mcp_server, query, tool

log = logging.getLogger(__name__)

CODING_RULES = """You are changing the source code of Iris, a personal voice assistant (Python 3.12 backend in src/iris with a
hexagonal architecture, React + Vite + Tailwind + shadcn frontend in frontend/). Rules:
- Read docs/arquitetura.md and the code around your change first, and follow the existing patterns.
- Code, names and commit messages always in English. No code comments, match the surrounding style.
- New capabilities for the assistant are Tool classes in src/iris/agent/tools registered in src/iris/app.py,
  and mentioned in src/iris/agent/prompts/system.md when the model needs to know about them.
- Add or update tests in tests/ and run them with the run_tests tool (there is no shell).
- Check your changes with git_status, and when the tests pass, commit with git_commit.
- Never push, never touch other repositories, never change files outside this folder.
- Finish with a short summary in Brazilian Portuguese of what you changed, in two or three sentences."""


@dataclass
class CodeJob:
    id: str
    instruction: str
    branch: str
    worktree: Path
    base: str = ""
    status: str = "running"
    summary: str = ""
    tests: str = ""
    changed_files: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "change"


class ClaudeCodeWorker:
    def __init__(
        self,
        repo: Path,
        python: Path,
        on_finished: Callable[[CodeJob], None],
        model: str = "sonnet",
        workspace: Path | None = None,
    ):
        self.repo = repo
        self.python = python
        self.on_finished = on_finished
        self.model = model
        self.workspace = workspace or repo.parent / "iris-work"
        self.jobs: dict[str, CodeJob] = {}

    async def _run_agent(self, prompt: str, options: ClaudeAgentOptions) -> str:
        result = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message.result or ""
        return result

    def analyze(self, question: str) -> str:
        options = ClaudeAgentOptions(
            cwd=str(self.repo),
            model=self.model,
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=25,
            system_prompt=(
                "You answer questions about the source code of Iris, a personal voice assistant, by reading it. "
                "Answer in Brazilian Portuguese, in at most four short sentences meant to be spoken aloud, "
                "without markdown, code blocks or file paths unless asked."
            ),
        )
        return asyncio.run(self._run_agent(question, options)) or "Não consegui analisar o código."

    def start(self, instruction: str) -> CodeJob:
        job_id = time.strftime("%H%M%S")
        branch = f"iris/{slugify(instruction)}-{job_id}"
        worktree = self.workspace / branch.replace("/", "-")
        self.workspace.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", branch, str(worktree), "HEAD", cwd=self.repo)
        job = CodeJob(job_id, instruction, branch, worktree, base=git("rev-parse", "HEAD", cwd=self.repo))
        self.jobs[job_id] = job
        threading.Thread(target=self._work, args=(job,), daemon=True).start()
        return job

    def _dev_server(self, job: CodeJob):
        @tool("run_tests", "Runs the project's pytest suite and returns the summary and failures", {})
        async def run_tests(args):
            return {"content": [{"type": "text", "text": self._run_tests(job.worktree, full=True)}]}

        @tool("git_status", "Shows changed files and the diff of the working tree", {})
        async def git_status(args):
            text = git("status", "--short", cwd=job.worktree) + "\n\n" + git("diff", cwd=job.worktree)[:6000]
            return {"content": [{"type": "text", "text": text or "No changes"}]}

        @tool("git_commit", "Stages every change and commits it on the current branch", {"message": str})
        async def git_commit(args):
            git("add", "-A", cwd=job.worktree)
            return {"content": [{"type": "text", "text": git("commit", "-m", args["message"], cwd=job.worktree)}]}

        return create_sdk_mcp_server("dev", tools=[run_tests, git_status, git_commit])

    def _work(self, job: CodeJob) -> None:
        options = ClaudeAgentOptions(
            cwd=str(job.worktree),
            model=self.model,
            tools=["Read", "Glob", "Grep", "Edit", "Write"],
            mcp_servers={"dev": self._dev_server(job)},
            allowed_tools=["Read", "Glob", "Grep", "Edit", "Write", "mcp__dev__run_tests", "mcp__dev__git_status", "mcp__dev__git_commit"],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=60,
            system_prompt=CODING_RULES,
        )
        try:
            job.summary = asyncio.run(self._run_agent(job.instruction, options))
            if git("status", "--porcelain", cwd=job.worktree):
                git("add", "-A", cwd=job.worktree)
                git("commit", "-m", f"feat: {job.instruction[:60]}", cwd=job.worktree)
            job.changed_files = [f for f in git("diff", "--name-only", job.base, "HEAD", cwd=job.worktree).splitlines() if f]
            job.tests = self._run_tests(job.worktree)
            if not job.changed_files:
                job.status = "no_changes"
            else:
                job.status = "ready" if job.tests.startswith("passed") else "tests_failed"
        except Exception as exc:
            log.exception("Code job %s failed", job.id)
            job.status = "failed"
            job.summary = str(exc)
        log.info("Code job %s finished: %s %s", job.id, job.status, job.changed_files)
        self.on_finished(job)

    def _run_tests(self, folder: Path, full: bool = False) -> str:
        result = subprocess.run(
            [str(self.python), "-m", "pytest", "-q"],
            cwd=str(folder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=300,
        )
        last = (result.stdout.strip().splitlines() or ["no output"])[-1]
        if full and result.returncode != 0:
            return f"failed: {last}\n{result.stdout[-4000:]}"
        return f"passed: {last}" if result.returncode == 0 else f"failed: {last}"

    def apply(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if job is None or job.status != "ready":
            return f"Change {job_id} is not ready to apply"
        if git("status", "--porcelain", cwd=self.repo):
            return "The main Iris folder has uncommitted changes, so nothing was applied"
        git("merge", "--ff-only", job.branch, cwd=self.repo)
        if any(f.startswith("frontend/") for f in job.changed_files):
            build = subprocess.run(
                "npm run build",
                cwd=str(self.repo / "frontend"),
                shell=True,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=300,
            )
            if build.returncode != 0:
                git("reset", "--hard", "ORIG_HEAD", cwd=self.repo)
                return "The interface build failed, so the change was rolled back"
        git("worktree", "remove", "--force", str(job.worktree), cwd=self.repo)
        job.status = "applied"
        return f"Applied {len(job.changed_files)} changed files from {job.branch}"

    def discard(self, job_id: str) -> str:
        job = self.jobs.pop(job_id, None)
        if job is None:
            return f"Change {job_id} not found"
        git("worktree", "remove", "--force", str(job.worktree), cwd=self.repo)
        git("branch", "-D", job.branch, cwd=self.repo)
        return f"Discarded {job.branch}"
