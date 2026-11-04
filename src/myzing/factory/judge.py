"""Judgment calls (scout, plan, pick, copy) as prompts with JSON answers.

Two backends:
- host (default): the prompt is written to <project>/pending/<task>.md and the run stops; the calling agent (or a
  person) answers with `zing factory answer` or the factory_answer MCP tool, then the run resumes.
- claude: Claude Code's headless CLI answers (`claude -p`); prompts and public contact sheets go to Anthropic.
Every answer is cached in <project>/answers/<task>.json, so a rerun never asks twice.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .network import CLAUDE, Network
from .tools import FactoryError

TASK = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
DEFAULT_MODEL = "claude-opus-5-5"
SYSTEM = "You are a precise social video editor. Reply with only the JSON object the user asks for."
# Measured on a real plan prompt: medium effort $0.055, low $0.019 (thinking 719 vs 0 tokens), both valid JSON.
EFFORT = {"scout": "medium", "plan": "medium", "pick": "medium", "copy": "low"}


class NeedsAnswer(Exception):
    def __init__(self, task: str, path: Path):
        super().__init__(f"{task} needs an answer: {path}")
        self.task, self.path = task, path


def parse(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("the answer has no JSON object")
    value = json.loads(text[a:b + 1])
    if not isinstance(value, dict):
        raise ValueError("the answer must be a JSON object")
    return value


def split_prompt(text: str, project: Path) -> tuple[str, list[str]]:
    root, images = project.resolve(), []
    while match := re.match(r"\A<!-- image: ([^\r\n]+) -->(?:\r?\n|$)", text):
        try:
            path = Path(match[1]).resolve()
            if path.is_relative_to(root):
                images.append(path.as_posix())
        except (OSError, ValueError):
            pass
        text = text[match.end():]
    return text, images


class Judge:
    def __init__(self, project: Path, backend: str = "host", model: str = DEFAULT_MODEL, retry_wait: float = 60.0):
        if backend not in ("host", "claude"):
            raise ValueError("judge must be 'host' or 'claude'")
        self.project, self.backend, self.model, self.retry_wait = Path(project), backend, model, retry_wait
        if backend == "claude":
            Network(self.project).check("Claude judge")

    def _paths(self, task: str) -> tuple[Path, Path]:
        if not TASK.match(task):
            raise ValueError(f"bad task id {task!r}")
        return self.project / "answers" / f"{task}.json", self.project / "pending" / f"{task}.md"

    def cached(self, task: str) -> dict | None:
        answer, _ = self._paths(task)
        return json.loads(answer.read_text(encoding="utf-8")) if answer.is_file() else None

    def ask(self, task: str, prompt: str, images: tuple[Path, ...] = ()) -> dict:
        answer, pending = self._paths(task)
        if answer.is_file():
            return json.loads(answer.read_text(encoding="utf-8"))
        cfg = self.project / "factory.json"
        local = images and cfg.is_file() and json.loads(cfg.read_text(encoding="utf-8")).get("visuals")
        if self.backend == "claude" and not local:
            return self.save(task, self._claude(task, prompt, bool(images)))
        pending.parent.mkdir(parents=True, exist_ok=True)
        head = "".join(f"<!-- image: {Path(p).resolve().as_posix()} -->\n" for p in images)
        pending.write_text(head + prompt, encoding="utf-8")
        raise NeedsAnswer(task, pending)

    def save(self, task: str, text: str | dict) -> dict:
        answer, pending = self._paths(task)
        value = text if isinstance(text, dict) else parse(text)
        answer.parent.mkdir(parents=True, exist_ok=True)
        answer.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
        pending.unlink(missing_ok=True)
        return value

    def forget(self, task: str) -> None:
        for path in self._paths(task):
            path.unlink(missing_ok=True)

    def pending(self) -> list[dict]:
        folder = self.project / "pending"
        out = []
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            text = path.read_text(encoding="utf-8")
            _, images = split_prompt(text, self.project)
            out.append({"task": path.stem, "prompt_path": str(path), "images": images})
        return out

    def _claude(self, task: str, prompt: str, images: bool) -> str:
        net = Network(self.project)
        net.check("Claude judge")
        self._paths(task)
        cfg = self.project / "factory.json"
        if images and cfg.is_file() and json.loads(cfg.read_text(encoding="utf-8")).get("visuals"):
            raise FactoryError("use the host judge to pick from your files")
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("--judge claude needs Claude Code's 'claude' CLI on PATH")
        # Lean call: Claude Code's default context (memory, skills, plugins, MCP instructions) measured ~150k
        # input tokens per call against a ~1.5k-token prompt; a short system prompt, no MCP servers, no skills,
        # only the Read tool when an image must be seen, and an empty working folder bring it to ~3k.
        cwd = self.project / ".judge"
        cwd.mkdir(parents=True, exist_ok=True)
        argv = [exe, "-p", "--model", self.model, "--output-format", "json", "--no-session-persistence",
                "--system-prompt", SYSTEM, "--strict-mcp-config", "--disable-slash-commands",
                "--setting-sources", "project", "--effort", EFFORT.get(task.split("-")[-1], "medium"),
                "--tools", "Read" if images else ""]
        if images:
            argv += ["--allowedTools", "Read"]
        last = ""
        for attempt in range(2):        # one retry: a refused or empty call usually goes through a minute later
            with net.request(CLAUDE, task):
                r = subprocess.run(argv, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=900,
                                   cwd=cwd)
            try:
                out = json.loads(r.stdout)
            except ValueError:
                out = {"result": r.stdout}
            text = str(out.get("result") or "")
            if r.returncode == 0 and "{" in text:
                self._ledger(task, out)
                return text
            last = (r.stderr or text)[-300:]
            if attempt == 0:
                time.sleep(self.retry_wait)
        raise RuntimeError(f"claude did not answer: {last}")

    def _ledger(self, task: str, out: dict) -> None:
        usage = out.get("usage") or {}
        row = {"task": task, "cost_usd": out.get("total_cost_usd"), "seconds": round((out.get("duration_ms") or 0) / 1000, 1),
               **{k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                             "output_tokens")}}
        path = self.project / "answers" / "_usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def usage(self) -> dict:
        path = self.project / "answers" / "_usage.jsonl"
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] if path.is_file() else []
        return {"calls": len(rows), "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4)}
