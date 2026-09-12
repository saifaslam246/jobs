"""Resolve where a posting really applies, and find a recruiting address if one exists.

Every board link (WeWorkRemotely, Arbeitnow, Jobicy...) points at the board, not the
employer. This follows that link one hop to recover two things, in order of how much
they are worth:

  1. THE REAL APPLY URL and which applicant tracking system it belongs to. This is the
     valuable half: a Greenhouse or Lever link is a form that a recruiter actually
     reads, and it beats a cold email to a general inbox every time.
  2. A RECRUITING EMAIL on the company's own site, if the company publishes one.

On (2) the rule is deliberately narrow, because the naive version is harmful:

  * Only role addresses are kept - jobs@, careers@, recruiting@, hr@, bewerbung@,
    talent@ and friends. These exist to receive exactly this mail.
  * A general inbox (info@, office@, hello@) is recorded as LOW confidence and never
    auto-sent. An application to info@ converts worse than the company's own form and
    is likelier to be marked spam, which costs sender reputation on the good mail too.
  * A personal address (firstname.lastname@) is never collected. Scraping a named
    individual's address off a website and cold-mailing it is a GDPR problem in the EU
    and reads as spam to the human on the other end.

For Austrian and German companies the Impressum is checked first: it is a legally
required page of published contact details, which makes it the cleanest source there is.

Runs in GitHub Actions, where there is real internet. The Claude session cannot reach
any of these hosts.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Boards and aggregators: a link here is not the employer.
BOARD_HOSTS = {
    "weworkremotely.com", "news.ycombinator.com", "arbeitnow.com", "arbeitnow.fr",
    "arbeitnow.co.uk", "jobicy.com", "himalayas.app", "remoteok.com", "remotive.com",
    "linkedin.com", "indeed.com", "glassdoor.com", "google.com", "adzuna.com",
}

# Applicant tracking systems: not the employer's domain, but a real application form.
ATS_HOSTS = {
    "greenhouse.io": "Greenhouse", "boards.greenhouse.io": "Greenhouse",
    "job-boards.greenhouse.io": "Greenhouse",
    "lever.co": "Lever", "jobs.lever.co": "Lever",
    "ashbyhq.com": "Ashby", "jobs.ashbyhq.com": "Ashby",
    "workable.com": "Workable", "apply.workable.com": "Workable",
    "personio.de": "Personio", "personio.com": "Personio", "jobs.personio.de": "Personio",
    "smartrecruiters.com": "SmartRecruiters", "recruitee.com": "Recruitee",
    "join.com": "Join", "bamboohr.com": "BambooHR", "teamtailor.com": "Teamtailor",
    "workdayjobs.com": "Workday", "myworkdayjobs.com": "Workday",
    "softgarden.io": "softgarden", "jobvite.com": "Jobvite", "breezy.hr": "Breezy",
}

ROLE_LOCALPARTS = {
    "jobs", "job", "career", "careers", "recruiting", "recruitment", "recruit",
    "hiring", "hr", "talent", "people", "apply", "application", "applications",
    "bewerbung", "bewerbungen", "personal", "personalabteilung", "karriere",
}
GENERAL_LOCALPARTS = {
    "info", "office", "hello", "hallo", "contact", "kontakt", "mail", "email",
    "team", "welcome", "enquiries", "inquiries", "admin", "help", "support",
}
JUNK_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "postmaster", "abuse", "privacy", "dpo",
    "datenschutz", "legal", "press", "presse", "marketing", "sales", "billing",
    "invoice", "webmaster", "security", "unsubscribe",
}

CONTACT_PATHS = [
    "/impressum", "/imprint", "/kontakt", "/contact", "/contact-us",
    "/careers", "/jobs", "/karriere", "/about", "/about-us", "",
]

MAX_FETCHES_PER_JOB = 5
POLITE_DELAY = 1.0


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def registrable(host: str) -> str:
    """Good-enough eTLD+1 for matching an address against a site."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac", "gov"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def detect_ats(url: str) -> str | None:
    h = host_of(url)
    for key, name in ATS_HOSTS.items():
        if h == key or h.endswith("." + key):
            return name
    return None


def is_board(url: str) -> bool:
    h = host_of(url)
    return any(h == b or h.endswith("." + b) for b in BOARD_HOSTS)


def classify_email(addr: str, site_host: str) -> tuple[str, int]:
    """Return (kind, confidence 0-100). kind is 'role', 'general' or 'reject'."""
    addr = addr.strip().lower()
    local, _, domain = addr.partition("@")
    if not domain or "." not in domain:
        return "reject", 0
    base = re.split(r"[+.]", local)[0]

    if local in JUNK_LOCALPARTS or base in JUNK_LOCALPARTS:
        return "reject", 0
    # a person's address: two name-ish parts, or a first name we cannot verify
    if local not in ROLE_LOCALPARTS and local not in GENERAL_LOCALPARTS:
        if re.fullmatch(r"[a-z]+[._-][a-z]+", local) or re.fullmatch(r"[a-z]{2,}", local):
            if base not in ROLE_LOCALPARTS and base not in GENERAL_LOCALPARTS:
                return "reject", 0

    on_site = registrable(domain) == registrable(site_host) if site_host else False
    if local in ROLE_LOCALPARTS or base in ROLE_LOCALPARTS:
        return "role", 90 if on_site else 65
    if local in GENERAL_LOCALPARTS or base in GENERAL_LOCALPARTS:
        return "general", 55 if on_site else 35
    return "reject", 0


def follow_to_employer(board_url: str) -> tuple[str | None, str | None]:
    """One hop from a board page to the real apply destination.

    Returns (apply_url, ats_name). Either may be None.
    """
    try:
        html = sources._get(board_url, retries=2).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        sources.log(f"  could not read board page: {e}")
        return None, None

    candidates: list[str] = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        if not href.startswith("http"):
            continue
        if is_board(href):
            continue
        ats = detect_ats(href)
        if ats:
            candidates.insert(0, href)      # an ATS link always wins
        elif re.search(r"(apply|career|jobs|stelle|bewerb)", href, re.I):
            candidates.append(href)
    if not candidates:
        return None, None
    best = candidates[0]
    return best, detect_ats(best)


def find_recruiting_email(site_url: str) -> tuple[str | None, str, int, str]:
    """Look for a role address on the company's own site.

    Returns (email, kind, confidence, page_it_came_from).
    """
    host = host_of(site_url)
    if not host or is_board(site_url) or detect_ats(site_url):
        return None, "", 0, ""
    origin = f"https://{host}"
    best: tuple[str | None, str, int, str] = (None, "", 0, "")

    for i, path in enumerate(CONTACT_PATHS):
        if i >= MAX_FETCHES_PER_JOB:
            break
        url = origin + path
        try:
            html = sources._get(url, retries=1).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - most of these paths will not exist
            continue
        time.sleep(POLITE_DELAY)
        found = set(sources.EMAIL_RE.findall(html))
        for m in re.finditer(r'mailto:([^"\'?>\s]+)', html, re.I):
            found.add(m.group(1))
        for addr in found:
            kind, conf = classify_email(addr, host)
            if kind == "reject":
                continue
            if conf > best[2]:
                best = (addr.strip().lower(), kind, conf, url)
        if best[1] == "role" and best[2] >= 90:
            break        # a role address on their own domain is as good as it gets
    return best


def enrich(job: dict) -> dict:
    """Fill in apply_url, ats and (maybe) a recruiting address. Never overwrites an
    address that came from the posting itself - that one is always better."""
    out = {"apply_url": job["url"], "ats": detect_ats(job["url"]),
           "company_domain": "", "email_source": "", "email_confidence": 0}

    if job.get("contact_emails"):
        out["email_source"] = "posting"
        out["email_confidence"] = 100
        if not out["ats"] and not is_board(job["url"]):
            out["company_domain"] = host_of(job["url"])
        return out

    if is_board(job["url"]):
        apply_url, ats = follow_to_employer(job["url"])
        if apply_url:
            out["apply_url"], out["ats"] = apply_url, ats
    else:
        out["ats"] = detect_ats(job["url"])

    target = out["apply_url"]
    if out["ats"] or is_board(target):
        return out                    # an ATS form is the route in; no email needed

    out["company_domain"] = host_of(target)
    email, kind, conf, page = find_recruiting_email(target)
    if email and kind == "role":
        job["contact_emails"] = [email]
        out.update(email_source=f"{kind} address on {page}", email_confidence=conf)
    elif email:
        # recorded so it is visible, but never used for unattended sending
        job["fallback_emails"] = [email]
        out.update(email_source=f"{kind} address on {page}", email_confidence=conf)
    return out


def main() -> int:
    matches = ROOT / "data" / "matches.json"
    jobs = json.loads(matches.read_text())
    jobs.sort(key=lambda j: -j["match"]["score"])
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    done = 0
    for j in jobs:
        if done >= budget:
            break
        if j.get("enrichment"):
            continue
        if j["match"]["verdict"] != "shortlist" and j["match"]["score"] < 45:
            continue
        sources.log(f"enriching {j['company'][:30]} - {j['title'][:40]}")
        try:
            j["enrichment"] = enrich(j)
        except Exception as e:  # noqa: BLE001 - one bad site must not stop the run
            sources.log(f"  failed: {e}")
            j["enrichment"] = {"error": str(e)[:200]}
        done += 1

    matches.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    with_ats = sum(1 for j in jobs if (j.get("enrichment") or {}).get("ats"))
    with_role = sum(1 for j in jobs
                    if (j.get("enrichment") or {}).get("email_confidence", 0) >= 65)
    print(json.dumps({"enriched": done, "with_ats_form": with_ats,
                      "with_role_email": with_role}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
