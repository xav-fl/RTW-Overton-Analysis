import json
import subprocess

import pytest

from overton import claude_cli, llm_assemble, llm_code
from test_llm_code import good_answer, project  # noqa: F401 - pytest fixture


def result_json(answer=None, **over) -> str:
    """The shape `claude -p --output-format json` prints."""
    res = {
        "type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn",
        "result": "", "structured_output": answer, "session_id": "s1",
        "total_cost_usd": 0.02,
        "usage": {"input_tokens": 400, "output_tokens": 250,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 11000},
        "modelUsage": {"claude-opus-5-5": {"inputTokens": 400}},
    }
    res.update(over)
    return json.dumps(res)


class FakeRun:
    def __init__(self, respond):
        self.respond = respond
        self.calls = []

    def __call__(self, args, stdin_text, cwd, timeout):
        self.calls.append((args, stdin_text, cwd))
        return self.respond(args, stdin_text)


def make(tmp_path, respond, system="SYSTEM PROMPT"):
    run = FakeRun(respond)
    cc = claude_cli.ClaudeCode(system, executable="claude.exe", run=run, workdir=tmp_path / "cc")
    return cc, run


ROW = {"custom_id": "W1", "user_message": "PAPER RECORD\nTITLE: T"}


def test_command_isolates_the_call(tmp_path):
    cc, run = make(tmp_path, lambda a, s: (0, result_json(good_answer()), ""))
    rec = cc(ROW, "k", "claude-opus-5-5", "medium")
    args, stdin_text, cwd = run.calls[0]
    assert args[:2] == ["claude.exe", "-p"]
    flags = dict(zip(args, args[1:]))
    assert flags["--output-format"] == "json"
    assert flags["--model"] == "claude-opus-5-5" and flags["--effort"] == "medium"
    assert flags["--tools"] == "" and flags["--setting-sources"] == ""
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    assert json.loads(flags["--json-schema"]) == llm_code.schema()
    assert (tmp_path / "cc" / "system.txt").read_text(encoding="utf-8") == "SYSTEM PROMPT"
    assert stdin_text == ROW["user_message"]
    assert list(cwd.iterdir()) == []          # empty working folder
    assert rec["status"] == "ok" and rec["route"] == "claude-code"
    assert rec["answer"]["item_type"] == "research_article"
    assert rec["answered_model"] == "claude-opus-5-5"
    assert rec["usage"]["cache_read_input_tokens"] == 11000


def test_answer_in_result_text_is_accepted(tmp_path):
    text = json.dumps(good_answer())
    cc, _ = make(tmp_path, lambda a, s: (0, result_json(None, result=text), ""))
    assert cc(ROW, "k", "m", "low")["status"] == "ok"


def test_unparseable_and_refusal(tmp_path):
    cc, _ = make(tmp_path, lambda a, s: (0, result_json(None, result="sorry, no"), ""))
    assert cc(ROW, "k", "m", "low")["status"] == "parse_error"
    cc, _ = make(tmp_path, lambda a, s: (0, result_json(None, stop_reason="refusal"), ""))
    assert cc(ROW, "k", "m", "low")["status"] == "refusal"


@pytest.mark.parametrize("message", ["Not logged in · Please run /login",
                                     "Claude usage limit reached. Your limit resets at 5pm"])
def test_sign_in_and_usage_limit_stop_the_run(tmp_path, message):
    out = result_json(None, is_error=True, result=message)
    cc, _ = make(tmp_path, lambda a, s: (1, out, ""))
    with pytest.raises(llm_code.ProviderStopped):
        cc(ROW, "k", "m", "low")


def test_other_failures_are_recorded_not_raised(tmp_path):
    cc, _ = make(tmp_path, lambda a, s: (1, "", "something broke"))
    rec = cc(ROW, "k", "m", "low")
    assert rec["status"] == "api_error" and "something broke" in rec["error"]

    def slow(a, s):
        raise subprocess.TimeoutExpired(a, 1)
    cc, _ = make(tmp_path, slow)
    assert "timeout" in cc(ROW, "k", "m", "low")["error"]

    def missing(a, s):
        raise FileNotFoundError("claude.exe")
    cc, _ = make(tmp_path, missing)
    with pytest.raises(llm_code.ProviderStopped, match="cannot run"):
        cc(ROW, "k", "m", "low")


def test_end_to_end_through_claude_code(project, tmp_path):  # noqa: F811
    def respond(args, user):
        n = sum(1 for line in user.splitlines() if ". affiliation:" in line)
        ans = good_answer(n_authors=n)
        return 0, result_json(ans), ""

    system = llm_code.system_prompt(project)
    cc, run = make(tmp_path, respond, system)
    df = llm_code.load_inputs(project)
    recs = llm_code.run_sync(project, cc, df, model="claude-opus-5-5", effort="medium",
                             workers=2, log=lambda *_: None)
    assert [r["status"] for r in recs] == ["ok"] * 3
    key = llm_code.run_key(system, "claude-opus-5-5", "medium")
    out = llm_assemble.assemble(project, key)
    assert set(out["llm_route"]) == {"claude-code"}
    assert (out["llm_coded_from"] != "not_coded").all()
    assert llm_code.usage_summary(recs)["claude_code_calls"] == 3


def test_find_executable_prefers_env(monkeypatch):
    monkeypatch.setenv(claude_cli.EXECUTABLE_ENV, r"C:\x\claude.exe")
    assert claude_cli.find_executable() == r"C:\x\claude.exe"
