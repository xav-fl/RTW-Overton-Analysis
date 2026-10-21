"""Stage 2 route through an installed Claude Code CLI (`claude -p`), with no API key.

Calls run under the Claude sign-in of whoever runs them (sign in once with
`claude auth login`). Each call:

- runs `claude -p` as a subprocess, with an argument list and a timeout;
- from an empty working folder this module creates, so no CLAUDE.md or other
  project file is picked up;
- with the codebook as the replacement system prompt (a file), the paper
  record on stdin, and the same JSON schema as the API route (`--json-schema`);
- with every tool, MCP server and settings file switched off, and no saved session.

Answers are written to the same response store as the API route, with
route "claude-code". Server-side refusal fallbacks and the Batches discount
are API features and do not apply here.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path

from . import llm_code

#: Override with the full path to claude.exe if it is not found automatically.
EXECUTABLE_ENV = "CLAUDE_CODE_EXE"
TIMEOUT = 600  # seconds per paper

#: Messages that mean no later call can succeed either: stop the run, resume later.
_AUTH_PHRASES = ("not logged in", "/login", "invalid api key", "oauth token",
                 "authentication", "unauthorized")
_LIMIT_PHRASES = ("usage limit", "limit reached", "out of extra usage", "credit balance",
                  "hit your limit")


def find_executable() -> str | None:
    """$CLAUDE_CODE_EXE, then `claude` on PATH, then the copy the desktop app installs."""
    exe = os.environ.get(EXECUTABLE_ENV) or shutil.which("claude")
    if exe:
        return exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found = glob.glob(os.path.join(local, "Claude-Data", "*", "claude-code", "*", "*",
                                       "claude.exe"))
        if found:
            return max(found, key=os.path.getmtime)
    return None


def classify(message: str) -> str | None:
    """'auth', 'limit', or None for a failure specific to this call."""
    text = (message or "").lower()
    if any(p in text for p in _AUTH_PHRASES):
        return "auth"
    if any(p in text for p in _LIMIT_PHRASES):
        return "limit"
    return None


_RUNNING: set = set()
_RUNNING_LOCK = threading.Lock()


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:  # pragma: no cover - already gone
            pass


def kill_running() -> None:
    with _RUNNING_LOCK:
        procs = list(_RUNNING)
    for p in procs:
        if p.poll() is None:
            _kill_tree(p)


def run_command(args: list[str], stdin_text: str, cwd: Path,
                timeout: float) -> tuple[int, str, str]:
    """Run without a shell; on timeout or Ctrl+C kill the whole process tree."""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **kwargs)
    with _RUNNING_LOCK:
        _RUNNING.add(proc)
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        _kill_tree(proc)
        raise
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(proc)
    return proc.returncode, out or "", err or ""


class ClaudeCode:
    """A `send` for llm_code.run_sync that answers through `claude -p`."""

    route = "claude-code"

    def __init__(self, system: str, executable: str | None = None, run=run_command,
                 timeout: float = TIMEOUT, workdir: str | Path | None = None):
        self.executable = executable or find_executable()
        if not self.executable:
            raise llm_code.ProviderStopped(
                f"Claude Code not found: install it, or set {EXECUTABLE_ENV} to claude.exe")
        self._run = run
        self.timeout = timeout
        root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="overton-cc-"))
        self.workdir = root / "work"      # cwd for every call; stays empty
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.system_file = root / "system.txt"
        self.system_file.write_text(system, encoding="utf-8")
        self.schema = json.dumps(llm_code.schema(), separators=(",", ":"))

    def command(self, model: str, effort: str) -> list[str]:
        return [
            self.executable, "-p",
            "--output-format", "json",
            "--system-prompt-file", str(self.system_file),
            "--exclude-dynamic-system-prompt-sections",
            "--json-schema", self.schema,
            "--model", model,
            "--effort", effort,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
        ]

    def __call__(self, row: dict, key: str, model: str, effort: str) -> dict:
        cid = row["custom_id"]
        try:
            code, out, err = self._run(self.command(model, effort), row["user_message"],
                                       self.workdir, self.timeout)
        except subprocess.TimeoutExpired:
            return llm_code.error_record(cid, key, model, effort, self.route,
                                         f"timeout: no answer after {self.timeout:g}s")
        except OSError as exc:
            raise llm_code.ProviderStopped(f"cannot run Claude Code: {exc}") from exc
        try:
            res = json.loads(out)
        except json.JSONDecodeError:
            res = None
        if not isinstance(res, dict):
            message = (err or out).strip()[-500:]
            kind = classify(message)
            if kind:
                raise llm_code.ProviderStopped(f"Claude Code {kind}: {message}")
            return llm_code.error_record(cid, key, model, effort, self.route,
                                         f"exit {code}, no JSON result: {message}")
        return self.record(res, cid, key, model, effort)

    def record(self, res: dict, cid: str, key: str, model: str, effort: str) -> dict:
        message = str(res.get("result") or "")
        if res.get("is_error"):
            kind = classify(message)
            if kind:
                raise llm_code.ProviderStopped(f"Claude Code {kind}: {message}")
        u = res.get("usage") or {}
        usage = {f: int(u.get(f) or 0) for f in llm_code.USAGE_FIELDS}
        answered = next(iter(res.get("modelUsage") or {}), None)
        stop = res.get("stop_reason")
        answer, status, error = None, "ok", ""
        if res.get("is_error"):
            status, error = "api_error", message[:500]
        elif stop == "refusal":
            status, error = "refusal", message[:200]
        else:
            answer = res.get("structured_output")
            if answer is None:
                try:
                    answer = json.loads(message)
                except json.JSONDecodeError as exc:
                    status, error = "parse_error", str(exc)
            if status == "ok" and not isinstance(answer, dict):
                status, error, answer = "parse_error", "answer is not a JSON object", None
        rec = llm_code.error_record(cid, key, model, effort, self.route, error)
        rec.update({"status": status, "answered_model": answered, "stop_reason": stop,
                    "usage": usage, "answer": answer,
                    "raw_text": None if answer else message[:2000],
                    "reported_cost_usd": res.get("total_cost_usd"),
                    "session_id": res.get("session_id")})
        return rec

    def close(self) -> None:
        shutil.rmtree(self.workdir.parent, ignore_errors=True)
