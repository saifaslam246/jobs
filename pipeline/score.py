"""Match scoring: rank raw postings against the master profile.

Produces data/matches.json - the ranked, deduplicated shortlist that the
dashboard renders and that CV tailoring works from.

Scoring is deliberately explainable: every job carries the reasons for its
score so a bad ranking can be traced and the weights fixed, rather than
being a black box.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile" / "master-profile.json"

# Signals that a posting is contract / part-time / project work.
CONTRACT_TERMS = [
    "contract", "contractor", "freelance", "freelancer", "part-time", "part time",
    "project-based", "project based", "b2b", "hourly", "consultant", "consulting",
    "temporary", "fractional", "short-term", "interim",
]
REMOTE_TERMS = ["remote", "anywhere", "worldwide", "distributed", "work from home", "wfh"]

# A technology in the TITLE is the role's primary stack, whatever the body lists as
# nice-to-haves. "Senior Full Stack Developer - PHP Laravel" is a PHP job that happens
# to mention React, not a React job.
PRIMARY_TECH_REJECT = [
    "php", "laravel", "symfony", "wordpress", "drupal", "magento",
    ".net", "c#", "asp.net", "dotnet", "rails", "ruby",
    "django", "java", "kotlin", "scala", "golang", "rust", "elixir",
    "salesforce", "sap", "sharepoint", "unity", "unreal", "solidity", "web3",
]
# Regions that exclude an Austria-based candidate outright.
REGION_EXCLUDE = [
    "latam", "latin america", "brazil", "argentina", "colombia", "mexico only",
    "india only", "philippines", "pakistan only", "nigeria", "kenya", "vietnam",
    "us only", "usa only", "united states only", "canada only", "australia only",
    "new zealand", "singapore only", "japan", "south korea",
]

# Terms that mean "we will not sponsor / must already be here".
VISA_BLOCKERS = [
    "must be authorized to work in the us", "us citizen", "u.s. citizen",
    "security clearance", "green card", "onsite only", "on-site only",
    "no remote", "must reside in the united states", "us-based only",
    "hybrid in", "relocation required",
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]+", " ", (s or "").lower())


def contains(hay: str, needle: str) -> bool:
    """Word-ish containment so 'go' does not match 'google'."""
    n = needle.lower().strip()
    if not n:
        return False
    if " " in n or any(c in n for c in "+#."):
        return n in hay
    return re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", hay) is not None


def days_old(posted: str) -> float | None:
    if not posted:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(posted.strip()[:len(datetime.now().strftime(fmt)) + 8], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except Exception:  # noqa: BLE001 - date formats in the wild are a mess
            continue
    try:
        dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:  # noqa: BLE001
        return None


def score_job(job: dict, m: dict) -> dict:
    title = norm(job.get("title", ""))
    tags = norm(" ".join(job.get("tags", [])))
    body = norm(job.get("description", ""))
    loc = norm(f"{job.get('location','')} {job.get('employment_type','')}")
    hay = f"{title} {tags} {body} {loc}"
    head = f"{title} {tags} {body[:600]}"

    reasons: list[str] = []
    rejects: list[str] = []

    # --- gate 1: does it touch the stack at all? ---
    matched_must = [k for k in m["must_have_any"] if contains(hay, k)]
    if not matched_must:
        return {"score": 0, "verdict": "reject", "reasons": ["no stack overlap"],
                "matched": [], "gaps": [], "flags": []}

    # --- gate 2: wrong primary stack (only when it dominates the headline) ---
    for term in m["hard_reject"]:
        if contains(title, term) or contains(norm(body[:400]), term):
            rejects.append(f"primary stack mismatch: {term}")
    # a non-JS technology named in the title is the role's primary stack, unless the
    # title also names one of his core technologies
    core_in_title = any(contains(title, k) for k in
                        ("react", "node", "node.js", "nodejs", "next.js", "typescript",
                         "javascript", "nestjs", "react native", "flutter", "angular"))
    if not core_in_title:
        for term in PRIMARY_TECH_REJECT:
            if contains(title, term):
                rejects.append(f"role is primarily {term}")
                break
    # --- gate 3: seniority out of range ---
    for term in m["seniority_reject"]:
        if contains(title, term) or contains(head, term):
            rejects.append(f"seniority mismatch: {term}")
    if rejects:
        return {"score": 0, "verdict": "reject", "reasons": rejects,
                "matched": matched_must, "gaps": [], "flags": []}

    score = 0.0

    # --- stack match (max 50) ---
    strong = []
    stack_pts = 0.0
    for k in m["strong_signals"]:
        if contains(title, k):
            stack_pts += 7
            strong.append(k)
        elif contains(tags, k):
            stack_pts += 5
            strong.append(k)
        elif contains(body, k):
            stack_pts += 3
            strong.append(k)
    # breadth matters on its own: a role naming six of his technologies is a better
    # fit than one naming the same two over and over.
    stack_pts += max(0, len(strong) - 2) * 2
    score += min(stack_pts, 50)
    if strong:
        reasons.append(f"stack match: {', '.join(strong[:10])}")

    # --- ecosystem fit (max 10, can go negative) ---
    js_core = ["javascript", "typescript", "node.js", "nodejs", "react", "next.js",
               "react native", "nestjs", "express", "vue", "angular"]
    other_backend = ["kotlin", "java", "golang", " go ", "rust", "scala", "c#", ".net",
                     "php", "ruby", "elixir", "clojure"]
    js_hits = sum(1 for k in js_core if contains(head, k))
    other_hits = sum(1 for k in other_backend if contains(head, k))
    if js_hits >= 2 and other_hits == 0:
        score += 10
        reasons.append("JS/TypeScript shop")
    elif js_hits >= 2 and other_hits <= 1:
        score += 5
    elif other_hits >= 2 and js_hits <= 1:
        score -= 12
        reasons.append("primarily a non-JS stack")

    # --- role shape (max 15) ---
    if any(contains(title, t) for t in ("full stack", "fullstack", "full-stack")):
        score += 10
        reasons.append("full-stack role")
    elif any(contains(title, t) for t in ("frontend", "front end", "front-end", "react", "mobile", "backend", "back end", "node")):
        score += 7
        reasons.append("core-stack role title")
    if any(contains(title, t) for t in ("junior", "mid-level", "mid level", "intermediate")):
        score += 5
    elif contains(title, "senior") or contains(title, "lead"):
        score += 2

    # --- contract / part-time preference (max 12) ---
    hit_contract = [t for t in CONTRACT_TERMS if contains(hay, t)]
    if hit_contract:
        score += 12
        reasons.append(f"contract/part-time signal: {', '.join(hit_contract[:4])}")

    # --- location & remote fit (max 12) ---
    remote_hit = [t for t in REMOTE_TERMS if contains(f"{loc} {title} {tags}", t)]
    loc_hit = [t for t in m["location_ok"] if contains(loc, t)]
    if remote_hit:
        score += 8
        reasons.append("remote")
    if any(t in loc_hit for t in ("austria", "vienna", "innsbruck", "europe", "eu", "emea", "cet", "germany")):
        score += 4
        reasons.append("EU/Austria friendly")
    elif loc_hit:
        score += 1

    # --- domain familiarity (max 8) ---
    dom = [d for d in m["domain_bonus"] if contains(hay, d)]
    if dom:
        score += min(len(dom) * 3, 8)
        reasons.append(f"familiar domain: {', '.join(dom[:3])}")

    # --- actionability (max 8) ---
    if job.get("contact_emails"):
        score += 6
        reasons.append("direct contact email in posting")
    if job.get("salary"):
        score += 2

    # --- freshness (max 10, can go negative) ---
    age = days_old(job.get("posted_at", ""))
    if age is not None:
        if age <= 2:
            score += 10
            reasons.append("posted in last 48h")
        elif age <= 7:
            score += 6
        elif age <= 21:
            score += 2
        elif age > 120:
            # a four-month-old posting is filled. A score penalty was not enough:
            # an old post with a perfect stack match still outranked fresh ones.
            return {"score": 0, "verdict": "reject",
                    "reasons": [f"posting is {int(age)} days old"],
                    "matched": matched_must, "gaps": [], "flags": []}
        elif age > 60:
            score -= 15
            reasons.append("stale posting (>60 days)")

    # --- region lock: a role restricted to a region he cannot work from ---
    region_lock = [r for r in REGION_EXCLUDE if contains(f"{loc} {title}", r)]
    if region_lock:
        score -= 30
        reasons.append(f"restricted to {region_lock[0]} - you cannot work from there")

    # --- flags: things to check before applying, not auto-rejects ---
    flags = [v for v in VISA_BLOCKERS if v in body]

    # --- gaps: what the JD wants that the profile does not obviously claim ---
    profile_terms = set(m["strong_signals"]) | set(m["must_have_any"])
    common_extras = [
        "graphql", "kubernetes", "terraform", "go", "rust", "java", "kotlin", "swift",
        "vue", "svelte", "django", "flask", "laravel", "rails", "elasticsearch",
        "kafka", "rabbitmq", "azure", "gcp", "tailwind", "jest", "cypress",
        "playwright", "figma", "storybook", "microservices", "ci/cd", "german",
    ]
    gaps = [k for k in common_extras if contains(hay, k) and k not in profile_terms]

    final = max(0, min(100, round(score)))
    verdict = "shortlist" if final >= m["min_score_to_shortlist"] else "watch"
    if flags and final < 75:
        verdict = "watch"
        reasons.append("eligibility flag - check before applying")

    return {"score": final, "verdict": verdict, "reasons": reasons,
            "matched": sorted(set(strong)), "gaps": gaps[:12], "flags": flags}


def dedupe(jobs: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for j in jobs:
        key = re.sub(r"\s+", " ", f"{norm(j.get('company',''))}|{norm(j.get('title',''))}").strip()
        prev = seen.get(key)
        if prev is None:
            seen[key] = j
            continue
        # keep the richer record, but remember every source it appeared on
        keep, drop = (j, prev) if len(j.get("description", "")) > len(prev.get("description", "")) else (prev, j)
        srcs = set(keep.get("also_seen_on", [])) | set(drop.get("also_seen_on", []))
        srcs.add(drop["source"])
        srcs.discard(keep["source"])
        keep["also_seen_on"] = sorted(srcs)
        seen[key] = keep
    return list(seen.values())


def run(raw_path: Path, out_path: Path) -> dict:
    profile = json.loads(PROFILE.read_text())
    m = profile["matching"]
    jobs = json.loads(raw_path.read_text())

    jobs = dedupe(jobs)
    scored = []
    for j in jobs:
        res = score_job(j, m)
        if res["verdict"] == "reject":
            continue
        j.update(match=res, status="new")
        scored.append(j)

    scored.sort(key=lambda x: (-x["match"]["score"], x.get("company", "")))
    out_path.write_text(json.dumps(scored, indent=2, ensure_ascii=False))

    stats = {
        "scanned": len(jobs),
        "kept": len(scored),
        "shortlist": sum(1 for s in scored if s["match"]["verdict"] == "shortlist"),
        "with_contact_email": sum(1 for s in scored if s.get("contact_emails")),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return stats


if __name__ == "__main__":
    import sys
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "jobs-raw.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "matches.json"
    print(json.dumps(run(raw, out), indent=2))
