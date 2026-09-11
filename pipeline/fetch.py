"""Daily pipeline entrypoint: fetch -> score -> merge state -> write digest.

Run by .github/workflows/daily-jobs.yml. Everything it produces is committed
back to the repo, which is how results reach the Claude session (whose own
container cannot reach these job APIs).

State is never clobbered: a job you already marked 'applied' keeps that status
on every subsequent run.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score as scorer  # noqa: E402
import sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

RAW = DATA / "jobs-raw.json"
MATCHES = DATA / "matches.json"
STATE = DATA / "applications.json"
DIGEST = DATA / "digest.md"
RUNLOG = DATA / "last-run.json"

# Statuses that must survive a refresh.
STICKY = {"shortlisted", "cv_ready", "applied", "replied", "interview", "rejected", "dismissed", "offer"}


def collect() -> tuple[list[dict], dict]:
    jobs: list[dict] = []
    report: dict = {}
    for name, fn in sources.ADAPTERS.items():
        try:
            got = fn()
            jobs.extend(got)
            report[name] = {"ok": True, "count": len(got)}
            sources.log(f"{name}: {len(got)} jobs")
        except Exception as e:  # noqa: BLE001 - one dead source must not kill the run
            report[name] = {"ok": False, "count": 0, "error": str(e)[:300]}
            sources.log(f"{name}: FAILED {e}")
            traceback.print_exc(file=sys.stderr)

    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if app_id and app_key:
        try:
            got = sources.adzuna(app_id, app_key)
            jobs.extend(got)
            report["adzuna"] = {"ok": True, "count": len(got)}
            sources.log(f"adzuna: {len(got)} jobs")
        except Exception as e:  # noqa: BLE001
            report["adzuna"] = {"ok": False, "count": 0, "error": str(e)[:300]}
    else:
        report["adzuna"] = {"ok": False, "count": 0, "error": "ADZUNA_APP_ID/KEY secrets not set - Austria/Germany coverage is reduced"}
    return jobs, report


def merge_state(scored: list[dict]) -> list[dict]:
    old = {}
    if STATE.exists():
        try:
            old = {j["id"]: j for j in json.loads(STATE.read_text())}
        except Exception:  # noqa: BLE001
            old = {}

    today = datetime.now(timezone.utc).date().isoformat()
    for j in scored:
        prev = old.get(j["id"])
        if prev and prev.get("status") in STICKY:
            j["status"] = prev["status"]
            j["notes"] = prev.get("notes", "")
            j["applied_at"] = prev.get("applied_at")
            j["cv_path"] = prev.get("cv_path")
            j["first_seen"] = prev.get("first_seen", today)
        else:
            j["status"] = "new"
            j["notes"] = ""
            j["applied_at"] = None
            j["cv_path"] = None
            j["first_seen"] = prev.get("first_seen", today) if prev else today

    # keep anything you already acted on, even if it dropped out of the feeds
    live = {j["id"] for j in scored}
    for jid, prev in old.items():
        if jid not in live and prev.get("status") in STICKY:
            prev["stale"] = True
            scored.append(prev)
    return scored


def write_digest(jobs: list[dict], stats: dict, report: dict) -> None:
    short = [j for j in jobs if j["match"]["verdict"] == "shortlist" and j["status"] == "new"]
    lines = [
        f"# Job digest - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**{stats['scanned']} scanned - {stats['kept']} relevant - {len(short)} new shortlist "
        f"- {stats['with_contact_email']} with a direct contact email**",
        "",
        "## New shortlist",
        "",
    ]
    if not short:
        lines.append("_Nothing new above the shortlist threshold this run._")
    for j in short[:40]:
        mail = f" - contact: `{j['contact_emails'][0]}`" if j.get("contact_emails") else ""
        lines += [
            f"### {j['match']['score']} | {j['title']} - {j['company']}",
            f"`{j['source']}` | {j.get('location') or 'n/a'} | {j.get('salary') or 'salary n/a'}{mail}",
            "",
            f"<{j['url']}>",
            "",
            f"- **Why:** {'; '.join(j['match']['reasons'][:4])}",
        ]
        if j["match"]["gaps"]:
            lines.append(f"- **CV needs to cover:** {', '.join(j['match']['gaps'][:8])}")
        if j["match"]["flags"]:
            lines.append(f"- **Check first:** {'; '.join(j['match']['flags'])}")
        lines.append("")

    lines += ["## Source health", ""]
    for name, r in sorted(report.items()):
        mark = "ok" if r["ok"] else "FAILED"
        extra = f" - {r.get('error','')}" if not r["ok"] else ""
        lines.append(f"- `{name}`: {mark} ({r['count']}){extra}")
    DIGEST.write_text("\n".join(lines))


def main() -> int:
    jobs, report = collect()
    RAW.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    sources.log(f"raw total: {len(jobs)}")

    stats = scorer.run(RAW, MATCHES)
    scored = json.loads(MATCHES.read_text())
    scored = merge_state(scored)

    MATCHES.write_text(json.dumps(scored, indent=2, ensure_ascii=False))
    STATE.write_text(json.dumps(scored, indent=2, ensure_ascii=False))
    write_digest(scored, stats, report)
    RUNLOG.write_text(json.dumps({"stats": stats, "sources": report}, indent=2))

    print(json.dumps({"stats": stats, "sources": report}, indent=2))
    healthy = sum(1 for r in report.values() if r["ok"])
    if healthy == 0:
        print("ERROR: every source failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
