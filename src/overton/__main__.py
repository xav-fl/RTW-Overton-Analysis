"""CLI: python -m overton {resolve,harvest,normalise,filter,report,all}.

Exit codes: 0 ok, 2 a gate failed, 3 OpenAlex budget or rate limit reached
(re-run the same command after midnight UTC; the harvest resumes).
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import client as cl
from . import filter as flt
from . import harvest, normalise, report, resolve, settings
from .settings import Paths


class GateFailed(SystemExit):
    def __init__(self, stage: str, problems: list[str]):
        print(f"\nGATE FAILED — {stage}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        super().__init__(2)


def _years(spec: str | None) -> list[int]:
    if not spec:
        return list(settings.YEARS)
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def _targets(paths: Paths, journals: list[str] | None, years: list[int]):
    res = resolve.load_resolved(paths)
    if journals:
        unknown = set(journals) - set(res["journal_key"])
        if unknown:
            raise GateFailed("harvest", [f"unknown journal keys: {sorted(unknown)}"])
        res = res[res["journal_key"].isin(journals)]
    bad = res[res["status"] != "ok"]
    if len(bad):
        raise GateFailed("harvest", [f"{k}: not resolved (status {s})"
                                     for k, s in zip(bad["journal_key"], bad["status"])])
    return [(r["journal_key"], r["openalex_source_id"], y)
            for r in res.to_dict("records") for y in years]


class _Usage:
    """Context manager: record OpenAlex allowance before/after a networked command."""

    def __init__(self, paths: Paths, command: str):
        self.paths, self.command = paths, command

    def __enter__(self):
        self.client = cl.OpenAlexClient()
        self.before = self.client.rate_limit()
        print(f"OpenAlex allowance remaining: ${self.before.get('daily_remaining_usd')} "
              f"(resets {self.before.get('resets_at')})")
        self.client.calls = self.client.attempts = 0
        return self.client

    def __exit__(self, *exc):
        try:
            after = self.client.rate_limit()
            self.client.calls -= 1
            self.client.attempts -= 1
        except cl.OpenAlexError:
            after = {}
        cl.log_usage(self.paths, self.command, self.client, self.before, after)
        return False


def cmd_resolve(paths: Paths) -> None:
    print("== Stage 2: resolve journals")
    with _Usage(paths, "resolve") as c:
        df = resolve.resolve(c, paths)
    for r in df.to_dict("records"):
        print(f"  {r['journal_key']:<12} {r['status']:<14} {r['openalex_source_id']:<12} "
              f"{r['openalex_display_name']}")
    problems = resolve.check_resolved(df)
    if problems:
        raise GateFailed("Stage 2 resolve", problems)
    print("  gate passed: all journals ok; aer and aea_pp distinct")


def _check_complete(rows: list[dict], stage: str) -> None:
    bad = [f"{r['journal_key']} {r['year']}: {r['status']} (expected {r['expected_count']}, "
           f"retrieved {r['retrieved_count']}, unique {r['unique_work_ids']}) {r.get('error', '')}"
           for r in rows if r["status"] != "complete"]
    if bad:
        raise GateFailed(stage, bad)


def cmd_harvest(paths: Paths, pilot: bool, journals: list[str] | None, years: str | None) -> None:
    if pilot:
        targets = _targets(paths, list(settings.PILOT_JOURNALS), list(settings.PILOT_YEARS))
        stage = "Stage 3 pilot harvest"
    else:
        targets = _targets(paths, journals, _years(years))
        stage = "Stage 4 harvest"
    print(f"== {stage}: {len(targets)} journal-years")
    with _Usage(paths, "harvest --pilot" if pilot else "harvest") as c:
        if not pilot:
            total, est = harvest.estimate(c, targets)
            paths.interim.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(est).to_csv(paths.estimate, index=False, encoding="utf-8")
            print(f"  works counted: {sum(r['count'] for r in est)}; "
                  f"estimated requests: {total} (limit {settings.REQUEST_BUDGET})")
            if total > settings.REQUEST_BUDGET:
                raise GateFailed(stage, [f"estimated {total} requests > {settings.REQUEST_BUDGET}"])
        rows = harvest.harvest(c, paths, targets)
    _check_complete(rows, stage)
    zero = [f"{r['journal_key']} {r['year']}" for r in rows if int(r["expected_count"]) == 0]
    print(f"  gate passed: {len(rows)} journal-years complete, "
          f"{sum(int(r['retrieved_count']) for r in rows)} works"
          + (f"; zero-count: {', '.join(zero)}" if zero else ""))


def cmd_normalise(paths: Paths) -> None:
    print("== Stage 5: normalise")
    w, a, problems = normalise.normalise(paths)
    print(f"  works.csv: {len(w)} rows; authorships.csv: {len(a)} rows")
    if problems:
        raise GateFailed("Stage 5 normalise", problems)
    d = w[w["doi"].notna()]
    print(f"  gate passed; duplicate DOIs: {int(d['doi'].duplicated(keep=False).sum())} works")


def cmd_filter(paths: Paths) -> None:
    print("== Stage 6: filter")
    print(flt.summary(flt.run(paths)))


def cmd_report(paths: Paths) -> None:
    print("== Stage 7: report")
    rel = report.run(paths)
    print(f"  release: {rel['n_dois']} DOIs in {rel['n_batches']} batch file(s)")
    print(f"  wrote {paths.run_report.relative_to(paths.root)}, "
          f"{paths.harvest_report.relative_to(paths.root)}, data/release/, data/review/")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="overton")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve")
    h = sub.add_parser("harvest")
    h.add_argument("--pilot", action="store_true")
    h.add_argument("--journals", help="comma-separated journal keys")
    h.add_argument("--years", help="e.g. 2016-2025 or 2020")
    for name in ("normalise", "filter", "report", "all"):
        sub.add_parser(name)
    args = p.parse_args(argv)
    paths = Paths()
    try:
        if args.command == "resolve":
            cmd_resolve(paths)
        elif args.command == "harvest":
            js = [j.strip() for j in args.journals.split(",")] if args.journals else None
            cmd_harvest(paths, args.pilot, js, args.years)
        elif args.command == "normalise":
            cmd_normalise(paths)
        elif args.command == "filter":
            cmd_filter(paths)
        elif args.command == "report":
            cmd_report(paths)
        elif args.command == "all":
            cmd_resolve(paths)
            cmd_harvest(paths, True, None, None)
            cmd_harvest(paths, False, None, None)
            cmd_normalise(paths)
            cmd_filter(paths)
            cmd_report(paths)
    except cl.BudgetExhausted as exc:
        print(f"\nSTOPPED: {exc}", file=sys.stderr)
        return 3
    except cl.KeyMissing as exc:
        print(f"\nSTOPPED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
