"""Build a per-job CV for every posting whose portal switch is on.

The master CV is never touched. `profile/cv/master/` is Saif's own file and the only
thing this script reads from it is nothing at all - it reads the profile, the same
source `build_cv.py` uses, and writes into `profile/cv/tailored/`. A job with the
switch off has no file here, so the portal and the mailer both fall back to the
master.

Tailoring reorders his existing material against the posting - the skills categories
it asks for first, the most relevant projects first, their job title mirrored in the
headline. It never writes a sentence he has not approved on the master.

    python profile/cv/tailor_switches.py            # build from data/tailor.json
    python profile/cv/tailor_switches.py --on ID    # turn one job on and build it
    python profile/cv/tailor_switches.py --off ID   # turn one job off and remove it

The switch state lives in the portal's database; `data/tailor.json` is the copy this
repo can read. Claude syncs the two.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cv import build_content, write_docx, write_pdf, write_txt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE = ROOT / "profile" / "master-profile.json"
MATCHES = ROOT / "data" / "matches.json"
SWITCHES = ROOT / "data" / "tailor.json"
TAILORED = ROOT / "profile" / "cv" / "tailored"

# The portal looks the file up by job id, so the name has to be derivable from the id
# alone - no company or title slug in it.
def base_name(job_id: str) -> str:
    return f"Saif_ur_Rehman_CV_{job_id}"


def load_switches() -> dict:
    if not SWITCHES.exists():
        return {}
    try:
        return {k: bool(v) for k, v in json.loads(SWITCHES.read_text()).items()}
    except Exception as e:  # noqa: BLE001 - a broken file must not silently build nothing
        raise SystemExit(f"{SWITCHES} is not readable JSON: {e}")


def save_switches(sw: dict) -> None:
    SWITCHES.parent.mkdir(parents=True, exist_ok=True)
    SWITCHES.write_text(json.dumps(dict(sorted(sw.items())), indent=2) + "\n")


ROLE_WORD = re.compile(
    r"\b(engineer|developer|architect|programmer|lead|consultant|scientist|specialist)",
    re.I)


def headline_for(job: dict, profile: dict) -> str:
    """Mirror their job title, keep his stack.

    ATS parsers score a title match, so the posting's title leads. Dropping his
    technologies to make room would cost the keyword hits that matter more, and a
    parenthetical like "(TypeScript)" reads oddly on a CV, so it comes off.
    """
    master = profile["identity"]["headline"]
    stack = master.partition("|")[2].strip() or master
    title = job.get("title") or ""
    # Some boards put the whole advert in the title field, and some put an emoji in
    # front of it. Neither belongs on a CV, so anything that does not look like a job
    # title leaves the master headline alone.
    title = re.sub(r"\s*\([^)]*\)", "", title)          # "(TypeScript)", "(f/m/d)"
    # "Company | Role | REMOTE | $250k raised" - take the part that names a job, not
    # the company that posted it.
    parts = [x for x in title.split("|") if x.strip()]
    title = next((x for x in parts if ROLE_WORD.search(x)), parts[0] if parts else "")
    title = re.sub(r"[^\x20-\x7e]+", " ", title).strip()  # emoji and the like
    title = re.sub(r"^\d+\s+", "", title)                 # "2 Full Stack AI Engineer"
    title = re.split(r",\s*\d|\s+\+\s+", title)[0]        # a second role tacked on
    title = re.sub(r"\s{2,}", " ", title).strip(" -,")
    if not title or len(title) > 60 or len(title.split()) > 8:
        return master
    return f"{title} | {stack}"


def build_for(job: dict, profile: dict) -> list[Path]:
    TAILORED.mkdir(parents=True, exist_ok=True)
    c = build_content(profile, job, headline_for(job, profile))
    base = base_name(job["id"])
    docx_p, pdf_p, txt_p = (TAILORED / f"{base}{ext}" for ext in (".docx", ".pdf", ".txt"))
    write_docx(c, docx_p)
    write_pdf(c, pdf_p)
    write_txt(c, txt_p)
    return [docx_p, pdf_p, txt_p]


def remove_for(job_id: str) -> int:
    n = 0
    for f in TAILORED.glob(base_name(job_id) + ".*"):
        f.unlink()
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--on", metavar="ID", help="turn the switch on for this job id and build it")
    ap.add_argument("--off", metavar="ID", help="turn the switch off and delete its file")
    ap.add_argument("--prebuild", type=int, default=12, metavar="N",
                    help="also build the N highest-scoring roles, so flipping the switch "
                         "in the portal shows a real file straight away instead of a "
                         "promise. 0 builds only what is switched on.")
    args = ap.parse_args()

    sw = load_switches()
    if args.on:
        sw[args.on] = True
    if args.off:
        sw[args.off] = False
    if args.on or args.off:
        save_switches(sw)

    profile = json.loads(PROFILE.read_text())
    jobs = {j["id"]: j for j in json.loads(MATCHES.read_text())}

    # Everything switched on, plus the best-scoring roles. Pre-building costs a few
    # hundred KB in the portal bundle and saves a round trip every time he flips a
    # switch; the file is ready before he asks for it.
    wanted = {jid for jid, on in sw.items() if on}
    if args.prebuild:
        ranked = sorted(jobs.values(),
                        key=lambda j: -((j.get("match") or {}).get("score") or 0))
        wanted |= {j["id"] for j in ranked[:args.prebuild]}

    built, removed, missing = [], [], []
    for job_id, on in sw.items():
        if not on and job_id not in wanted:
            removed += [job_id] if remove_for(job_id) else []

    for job_id in sorted(wanted):
        job = jobs.get(job_id)
        if job is None:
            missing.append(job_id)
            continue
        build_for(job, profile)
        built.append(f"{job_id}  {job.get('title', '?')} @ {job.get('company', '?')}")

    # A file left behind for a job that is no longer switched on would keep being
    # attached, so anything not explicitly on gets cleared.
    for f in sorted(TAILORED.glob("Saif_ur_Rehman_CV_*")):
        jid = f.stem[len("Saif_ur_Rehman_CV_"):]
        if jid not in wanted:
            f.unlink()

    print(json.dumps({
        "switches_on": sum(1 for v in sw.values() if v),
        "built": built,
        "cleared": removed,
        "not_in_matches": missing,
        "master_untouched": True,
    }, indent=2))


if __name__ == "__main__":
    main()
