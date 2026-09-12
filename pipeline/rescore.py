"""Re-score the last harvest without re-fetching.

Scoring weights get tuned against real postings, and refetching 2,500 jobs to test a
weight change is both slow and rude to the source APIs. This re-runs score.py over the
committed data/jobs-raw.json and merges your pipeline state back in, exactly as the
daily run would.
"""
from pathlib import Path

from fetch import DIGEST, MATCHES, RAW, RUNLOG, STATE, merge_state, write_digest  # noqa: F401
import json
import score as scorer

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    stats = scorer.run(RAW, MATCHES)
    scored = merge_state(json.loads(MATCHES.read_text()))
    MATCHES.write_text(json.dumps(scored, indent=2, ensure_ascii=False))
    STATE.write_text(json.dumps(scored, indent=2, ensure_ascii=False))
    prev = json.loads(RUNLOG.read_text()) if RUNLOG.exists() else {"sources": {}}
    write_digest(scored, stats, prev.get("sources", {}))
    print(json.dumps(stats, indent=2))
