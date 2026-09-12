"""Build a standalone snapshot of the portal.

portal/job-desk.html is the live page: it reads jobs from the artifact database and
keeps your status there. This produces the same page with the current harvest baked in
as a `window.__SEED__` literal, so it opens from disk or from any static host with no
database behind it. Status changes in a snapshot live in that browser's localStorage.

    python portal/build_snapshot.py [--limit 60] [--out portal/snapshot.html]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "portal" / "job-desk.html"
MATCHES = ROOT / "data" / "matches.json"
QUEUE = ROOT / "outreach" / "queue"


def job_doc(j: dict) -> dict:
    m = j["match"]
    return {
        "id": j["id"],
        "title": j["title"][:200],
        "company": j["company"][:120],
        "source": j["source"],
        "url": j["url"],
        "location": (j.get("location") or "")[:120],
        "salary": (j.get("salary") or "")[:80],
        "posted_at": j.get("posted_at", ""),
        "score": m["score"],
        "verdict": m["verdict"],
        "reasons": m["reasons"][:8],
        "matched": m["matched"][:14],
        "gaps": m["gaps"][:12],
        "flags": m["flags"][:6],
        "contact_emails": (j.get("contact_emails") or [])[:3],
        "is_contract": any("contract/part-time" in r for r in m["reasons"]),
        "description": (j.get("description") or "")[:4500],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", default=str(ROOT / "portal" / "snapshot.html"))
    args = ap.parse_args()

    jobs = json.loads(MATCHES.read_text())
    jobs.sort(key=lambda j: -j["match"]["score"])
    seed = {
        "generated_at": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
        "jobs": [job_doc(j) for j in jobs[:args.limit]],
        "outbox": [json.loads(f.read_text()) for f in sorted(QUEUE.glob("*.json"))],
    }

    html = SOURCE.read_text()
    # </script> inside the data would close the tag early
    blob = json.dumps(seed, ensure_ascii=False).replace("</", "<\\/")
    inject = f'<script>window.__SEED__ = {blob};</script>\n'
    marker = "<script>\n(function(){"
    if marker not in html:
        raise SystemExit("could not find the page's main script block to inject before")
    html = html.replace(marker, inject + marker, 1)

    out = Path(args.out)
    out.write_text(html)
    print(json.dumps({
        "out": str(out),
        "jobs": len(seed["jobs"]),
        "drafts": len(seed["outbox"]),
        "bytes": out.stat().st_size,
    }, indent=2))


if __name__ == "__main__":
    main()
