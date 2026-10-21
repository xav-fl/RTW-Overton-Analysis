"""Stage 2: code paper characteristics with Claude (network: Anthropic API or Claude Code).

One request per paper. The system prompt is the codebook plus the JEL taxonomy,
identical on every request so it is cached; the user message is the paper
record. Answers are constrained to a JSON schema and validated again here.

Every response is appended to data/interim/llm/responses.jsonl with its run
key (a hash of the prompt, schema, model and effort). Re-running skips papers
that already have a valid answer under the same run key, so an interrupted run
resumes, and changing the codebook starts a fresh set without losing the old
one. Three routes write the same records: `run_sync` with `api_sender`
(concurrent API requests, full price), `run_sync` with claude_cli.ClaudeCode
(`claude -p` under the user's Claude sign-in, no API key), and
`submit_batches` / `collect_batches` (Message Batches, half price, results
within 24 hours).

The API routes read ANTHROPIC_API_KEY (or any credential the SDK resolves).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import pandas as pd

from . import features, settings
from .settings import Paths

#: Bump when the wording of `user_message` changes; it is part of the run key.
USER_TEMPLATE_VERSION = "u1"

ITEM_TYPES = ["research_article", "review_article", "non_research"]
RESEARCH_TYPES = ["theoretical", "empirical", "theory_and_empirical",
                  "econometric_methods", "review_or_synthesis", "other"]
EMPIRICAL_DESIGNS = ["experimental", "quasi_experimental", "structural",
                     "descriptive_or_correlational", "forecasting_or_calibration",
                     "not_empirical"]
POLICY_CATEGORIES = ["proposes_novel_policy", "causal_effect_of_policy", "descriptive_fact",
                     "unintended_consequences", "predicts_effects_with_models",
                     "cost_benefit_or_welfare", "identifies_mechanisms",
                     "impacts_on_specific_groups"]
POLICY_REFERENCES = ["none", "existing_policy", "proposed_or_hypothetical_policy", "both"]
DISCIPLINES = ["economics", "finance_accounting", "business_management",
               "political_science_public_policy", "sociology_demography",
               "psychology_behavioral", "law", "statistics_mathematics",
               "computer_science_engineering", "medicine_public_health",
               "natural_environmental_science", "other", "unknown"]

#: USD per million tokens: (input, output, cache read). Cache writes bill at
#: 1.25x input; the Batches API halves everything.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25
BATCH_DISCOUNT = 0.5
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_RETRIES = 8
USAGE_FIELDS = ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens")


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def schema() -> dict:
    scale = {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    return _obj({
        "item_type": {"type": "string", "enum": ITEM_TYPES},
        "topic_label": {"type": "string"},
        "jel_codes": {"type": "array", "items": {"type": "string"}},
        "research_type": {"type": "string", "enum": RESEARCH_TYPES},
        "empirical_design": {"type": "string", "enum": EMPIRICAL_DESIGNS},
        "policy_categories": _obj({c: {"type": "boolean"} for c in POLICY_CATEGORIES}),
        "primary_policy_category": {"type": "string", "enum": POLICY_CATEGORIES + ["none"]},
        "policy_reference": {"type": "string", "enum": POLICY_REFERENCES},
        "jargon": scale,
        "sentence_complexity": scale,
        "author_disciplines": {"type": "array", "items": _obj({
            "author": {"type": "integer"},
            "discipline": {"type": "string", "enum": DISCIPLINES},
        })},
        "notes": {"type": "string"},
    })


def system_prompt(paths: Paths) -> str:
    codebook = paths.codebook.read_text(encoding="utf-8").strip()
    taxonomy = paths.jel_taxonomy.read_text(encoding="utf-8").strip()
    return f"{codebook}\n\nJEL TAXONOMY (code | title)\n{taxonomy}\n"


def run_key(system: str, model: str, effort: str) -> str:
    h = hashlib.sha256()
    for part in (system, json.dumps(schema(), sort_keys=True), USER_TEMPLATE_VERSION,
                 model, effort):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:12]


def custom_id(openalex_id: str) -> str:
    """'https://openalex.org/W123' -> 'W123' (Batches allow [A-Za-z0-9_-]{1,64})."""
    return openalex_id.rsplit("/", 1)[-1]


def user_message(paper: dict, authors: list[dict], use_abstract: bool) -> str:
    lines = ["PAPER RECORD",
             f"TITLE: {paper.get('title') or '(none)'}",
             f"JOURNAL: {paper.get('source_display_name')} ({paper.get('publication_year')})",
             f"ABSTRACT: {paper['abstract_clean'] if use_abstract else 'none'}"]
    sent = authors[:features.MAX_AUTHORS_SENT]
    if not sent:
        lines.append("AUTHORS: none listed")
    else:
        lines.append("AUTHORS (affiliation as printed; institutions as matched by OpenAlex):")
        for i, a in enumerate(sent, start=1):
            lines.append(f"{i}. affiliation: {a['affiliation'] or '(none)'} | "
                         f"institutions: {a['institutions'] or '(none)'}")
        if len(authors) > len(sent):
            lines.append(f"({len(authors) - len(sent)} further authors not listed; "
                         f"code only the {len(sent)} above)")
    return "\n".join(lines)


def request_params(system: str, user: str, model: str, effort: str) -> dict:
    """Body of one Messages request, shared by the sync and batch routes."""
    return {
        "model": model,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": schema()}},
        "fallbacks": "default",
    }


# -- inputs -------------------------------------------------------------------

def load_inputs(paths: Paths) -> pd.DataFrame:
    """Papers with their cleaned abstract, author list and user message."""
    papers = pd.read_csv(paths.papers_stage1, low_memory=False)
    feats = features.paper_features(papers)
    df = papers.merge(feats, on="openalex_id", how="left", validate="one_to_one")
    auths = features.author_affiliations(
        pd.read_csv(paths.authorships_stage1, low_memory=False))
    msgs, n_sent = [], []
    for r in df.to_dict("records"):
        a = auths.get(r["openalex_id"], [])
        msgs.append(user_message(r, a, bool(r["has_usable_abstract"])))
        n_sent.append(min(len(a), features.MAX_AUTHORS_SENT))
    df["user_message"] = msgs
    df["n_authors_sent"] = n_sent
    df["custom_id"] = df["openalex_id"].map(custom_id)
    # A stable pseudo-random order, so `--limit N` is a spread across journals and years.
    df["_order"] = df["custom_id"].map(lambda s: hashlib.sha256(s.encode()).hexdigest())
    return df.sort_values("_order").drop(columns="_order").reset_index(drop=True)


# -- response store -----------------------------------------------------------

class Store:
    """Append-only JSONL of every answer; the latest valid one per paper and run key counts."""

    def __init__(self, paths: Paths):
        self.path = paths.llm_responses
        self._lock = threading.Lock()

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def done(self, key: str) -> set[str]:
        return {r["custom_id"] for r in self.records()
                if r["run_key"] == key and r["status"] == "ok"}

    def append(self, rec: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _usage(msg) -> dict:
    u = getattr(msg, "usage", None)
    return {f: int(getattr(u, f, 0) or 0) for f in USAGE_FIELDS}


def record_from_message(msg, cid: str, key: str, model: str, effort: str,
                        route: str, batch_id: str | None = None) -> dict:
    """Turn one API message into a store record, classifying what came back."""
    stop = getattr(msg, "stop_reason", None)
    text = "".join(getattr(b, "text", "") for b in (msg.content or [])
                   if getattr(b, "type", "") == "text")
    parsed, status, error = None, "ok", ""
    if stop == "refusal":
        status = "refusal"
        details = getattr(msg, "stop_details", None)
        error = str(getattr(details, "category", "") or "")
    elif stop == "max_tokens":
        status, error = "max_tokens", "output cut off at max_tokens"
    else:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            status, error = "parse_error", str(exc)
    return {
        "custom_id": cid, "run_key": key, "status": status, "error": error,
        "requested_model": model, "answered_model": getattr(msg, "model", None),
        "effort": effort, "codebook_version": settings.LLM_CODEBOOK_VERSION,
        "route": route, "batch_id": batch_id, "stop_reason": stop,
        "usage": _usage(msg), "answer": parsed, "raw_text": None if parsed else text,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def error_record(cid: str, key: str, model: str, effort: str, route: str,
                 error: str, batch_id: str | None = None) -> dict:
    return {
        "custom_id": cid, "run_key": key, "status": "api_error", "error": error[:500],
        "requested_model": model, "answered_model": None, "effort": effort,
        "codebook_version": settings.LLM_CODEBOOK_VERSION, "route": route,
        "batch_id": batch_id, "stop_reason": None,
        "usage": dict.fromkeys(USAGE_FIELDS, 0), "answer": None, "raw_text": None,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# -- validation ---------------------------------------------------------------

def validate(answer: dict, n_authors_sent: int, jel_valid: set[str]) -> tuple[dict, list[str]]:
    """Normalise an answer and list what is wrong with it (nothing is dropped silently)."""
    problems: list[str] = []
    codes, bad = [], []
    for c in answer.get("jel_codes") or []:
        c = str(c).strip().upper()
        (codes if c in jel_valid else bad).append(c)
    codes = list(dict.fromkeys(codes))
    if bad:
        problems.append(f"invalid JEL codes dropped: {', '.join(bad)}")
    if len(codes) > 3:
        problems.append(f"{len(codes)} JEL codes; kept the first 3")
        codes = codes[:3]
    if not codes:
        problems.append("no valid JEL code")
    cats = answer.get("policy_categories") or {}
    primary = answer.get("primary_policy_category")
    if primary not in (None, "none") and not cats.get(primary):
        problems.append(f"primary_policy_category {primary} not marked yes")
    if primary == "none" and any(cats.values()):
        problems.append("primary_policy_category none but a category is yes")
    disc = {int(d["author"]): d["discipline"] for d in answer.get("author_disciplines") or []}
    if sorted(disc) != list(range(1, n_authors_sent + 1)):
        problems.append(f"author_disciplines covers {sorted(disc)}, expected 1..{n_authors_sent}")
    out = dict(answer)
    out["jel_codes"] = codes
    out["author_disciplines"] = [disc.get(i, "unknown") for i in range(1, n_authors_sent + 1)]
    return out, problems


def jel_valid_codes(paths: Paths) -> set[str]:
    return set(pd.read_csv(paths.jel_codes)["jel_code"].str.strip().str.upper())


# -- cost ---------------------------------------------------------------------

def cost_usd(usage: dict, model: str, batch: bool) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    inp, out, read = prices
    usd = (usage.get("input_tokens", 0) * inp
           + usage.get("cache_creation_input_tokens", 0) * inp * CACHE_WRITE_MULTIPLIER
           + usage.get("cache_read_input_tokens", 0) * read
           + usage.get("output_tokens", 0) * out) / 1_000_000
    return usd * (BATCH_DISCOUNT if batch else 1.0)


def usage_summary(records: Iterable[dict]) -> dict:
    """Token totals and cost at API prices. Claude Code calls are covered by the
    sign-in's plan, not billed per token, so `usd` for them is only the API
    equivalent; `claude_code_calls` says how many there were."""
    tot = dict.fromkeys(USAGE_FIELDS, 0)
    usd, n, n_cc = 0.0, 0, 0
    for r in records:
        n += 1
        n_cc += r["route"] == "claude-code"
        for f in USAGE_FIELDS:
            tot[f] += r["usage"].get(f, 0)
        c = cost_usd(r["usage"], r["answered_model"] or r["requested_model"],
                     r["route"] == "batch")
        usd += c or 0.0
    return {"calls": n, "claude_code_calls": n_cc, **tot, "usd": round(usd, 4),
            "usd_per_call": round(usd / n, 5) if n else None}


# -- client -------------------------------------------------------------------

class ProviderStopped(RuntimeError):
    """The API will refuse every further request (credit, key, permission)."""


_STOP_PHRASES = ("credit balance", "usage limit", "spend limit")


def stop_reason(exc: BaseException) -> str | None:
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if status == 402 or "billing" in msg or any(p in msg for p in _STOP_PHRASES):
        return "out of credit"
    if status == 401:
        return "API key rejected"
    if status == 403:
        return "API key lacks permission"
    return None


def make_client():
    from anthropic import Anthropic
    return Anthropic(max_retries=MAX_RETRIES)


# -- routes -------------------------------------------------------------------

def select(df: pd.DataFrame, done: set[str], limit: int | None,
           ids: set[str] | None) -> pd.DataFrame:
    todo = df[~df["custom_id"].isin(done)]
    if ids is not None:
        todo = todo[todo["custom_id"].isin(ids)]
    return todo.head(limit) if limit else todo


def api_sender(client, system: str):
    """A `send` for run_sync that answers through the Messages API."""

    def send(row: dict, key: str, model: str, effort: str) -> dict:
        params = request_params(system, row["user_message"], model, effort)
        try:
            msg = client.beta.messages.create(betas=[FALLBACK_BETA], **params)
        except Exception as exc:  # noqa: BLE001 - classified below, then recorded
            reason = stop_reason(exc)
            if reason:
                raise ProviderStopped(f"{reason}: {exc}") from exc
            return error_record(row["custom_id"], key, model, effort, "sync",
                                f"{type(exc).__name__}: {exc}")
        return record_from_message(msg, row["custom_id"], key, model, effort, "sync")

    return send


def run_sync(paths: Paths, send, df: pd.DataFrame, *, model: str, effort: str,
             workers: int = settings.LLM_WORKERS, log=print) -> list[dict]:
    """Code each row of df concurrently with `send(row, key, model, effort) -> record`.

    `send` is api_sender(...) or a claude_cli.ClaudeCode; it raises ProviderStopped
    when no further call can succeed, which stops the run. Returns the records written.
    """
    key = run_key(system_prompt(paths), model, effort)
    store = Store(paths)
    written: list[dict] = []
    stopped: list[str] = []

    def one(row: dict) -> dict:
        if stopped:
            return {}
        try:
            rec = send(row, key, model, effort)
        except ProviderStopped as exc:
            stopped.append(str(exc))
            return {}
        store.append(rec)
        return rec

    rows = df.to_dict("records")
    # The first request writes the prompt cache; sending it alone lets the rest read it.
    first, rest = rows[:1], rows[1:]
    for row in first:
        rec = one(row)
        if rec:
            written.append(rec)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, r) for r in rest]
        for i, fut in enumerate(as_completed(futures), start=2):
            rec = fut.result()
            if rec:
                written.append(rec)
                if i % 50 == 0 or i == len(rows):
                    log(f"  {i}/{len(rows)} answered")
    if stopped:
        raise ProviderStopped(stopped[0])
    return written


def _batch_state(paths: Paths) -> list[dict]:
    if not paths.llm_batches.exists():
        return []
    with paths.llm_batches.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["batch_id"]] = {**latest.get(r["batch_id"], {}), **r}
    return list(latest.values())


def _append_batch_state(paths: Paths, rec: dict) -> None:
    paths.llm.mkdir(parents=True, exist_ok=True)
    with paths.llm_batches.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def pending_ids(paths: Paths, key: str) -> set[str]:
    """Papers in submitted batches for this run key whose results are not collected yet."""
    return {cid for b in _batch_state(paths)
            if b["run_key"] == key and not b.get("collected") for cid in b["custom_ids"]}


def submit_batches(paths: Paths, client, df: pd.DataFrame, *, model: str, effort: str,
                   chunk: int = settings.LLM_BATCH_CHUNK, log=print) -> list[str]:
    from anthropic.types.beta.messages.batch_create_params import Request

    system = system_prompt(paths)
    key = run_key(system, model, effort)
    ids = []
    rows = df.to_dict("records")
    for start in range(0, len(rows), chunk):
        part = rows[start:start + chunk]
        reqs = [Request(custom_id=r["custom_id"],
                        params=request_params(system, r["user_message"], model, effort))
                for r in part]
        try:
            batch = client.beta.messages.batches.create(requests=reqs, betas=[FALLBACK_BETA])
        except Exception as exc:  # noqa: BLE001
            reason = stop_reason(exc)
            raise ProviderStopped(f"{reason or type(exc).__name__}: {exc}") from exc
        _append_batch_state(paths, {
            "batch_id": batch.id, "run_key": key, "model": model, "effort": effort,
            "n": len(part), "custom_ids": [r["custom_id"] for r in part],
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "collected": False})
        log(f"  submitted {batch.id}: {len(part)} requests")
        ids.append(batch.id)
    return ids


def collect_batches(paths: Paths, client, log=print) -> dict:
    """Store results of every ended, uncollected batch. Returns counts by state."""
    store = Store(paths)
    counts = {"ended": 0, "in_progress": 0, "records": 0}
    for b in _batch_state(paths):
        if b.get("collected"):
            continue
        info = client.beta.messages.batches.retrieve(b["batch_id"])
        if info.processing_status != "ended":
            counts["in_progress"] += 1
            rc = info.request_counts
            log(f"  {b['batch_id']}: {info.processing_status} "
                f"({rc.processing} processing, {rc.succeeded} succeeded)")
            continue
        seen = set()
        for res in client.beta.messages.batches.results(b["batch_id"]):
            seen.add(res.custom_id)
            kind = res.result.type
            if kind == "succeeded":
                rec = record_from_message(res.result.message, res.custom_id, b["run_key"],
                                          b["model"], b["effort"], "batch", b["batch_id"])
            else:
                err = getattr(getattr(res.result, "error", None), "error", None)
                rec = error_record(res.custom_id, b["run_key"], b["model"], b["effort"],
                                   "batch", f"{kind}: {err}", b["batch_id"])
            store.append(rec)
            counts["records"] += 1
        missing = set(b["custom_ids"]) - seen
        for cid in sorted(missing):
            store.append(error_record(cid, b["run_key"], b["model"], b["effort"], "batch",
                                      "no result returned", b["batch_id"]))
        _append_batch_state(paths, {"batch_id": b["batch_id"], "collected": True,
                                    "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                  time.gmtime())})
        counts["ended"] += 1
        log(f"  {b['batch_id']}: collected {len(seen)} results"
            + (f", {len(missing)} missing" if missing else ""))
    return counts
