"""Job source adapters.

Each adapter returns a list of jobs in the normalised schema defined in
normalise(). Adapters are intentionally defensive: a source that changes
shape or goes down logs a warning and returns [] rather than killing the run.

NOTE: these run inside GitHub Actions, which has unrestricted internet.
The Claude session container cannot reach these hosts (egress policy), which
is exactly why fetching is a scheduled Action that commits data to the repo.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; job-portal/1.0; +https://github.com/saifaslam246/jobs)"
TIMEOUT = 45

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
TAG_RE = re.compile(r"<[^>]+>")


def log(msg: str) -> None:
    print(f"[sources] {msg}", file=sys.stderr, flush=True)


def _get(url: str, headers: dict | None = None, retries: int = 3) -> bytes:
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - any network error is retryable here
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {retries} attempts: {url} ({last})")


def _json(url: str, headers: dict | None = None):
    return json.loads(_get(url, headers).decode("utf-8", "replace"))


def strip_html(s: str | None) -> str:
    """HTML (or HTML-escaped HTML) to readable plain text.

    Unescaping has to happen BEFORE tags are stripped, and again after. Some feeds
    (Arbeitnow among them) return HTML that is itself HTML-escaped - "&lt;h2&gt;" -
    so stripping first leaves the tags untouched and the later unescape reveals them
    as literal markup in the posting. Unescape up to three times, since a value that
    has been round-tripped through two systems can be doubly escaped, then strip.
    """
    if not s:
        return ""
    for _ in range(3):
        prev = s
        s = html.unescape(s)
        if s == prev:
            break
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|h[1-6]|tr)>", "\n\n", s, flags=re.I)
    s = re.sub(r"</li>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def find_emails(*texts: str | None) -> list[str]:
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        for m in EMAIL_RE.findall(t):
            m = m.strip(".,;:)")
            low = m.lower()
            # drop obvious non-contact addresses
            if any(x in low for x in ("example.com", "sentry.io", "@2x", ".png", ".jpg", "wixpress")):
                continue
            # accommodations and accessibility inboxes exist for a legal purpose; an
            # application sent there is worse than one not sent at all
            if any(x in low.split("@")[0] for x in
                   ("accommodation", "accessibility", "ada-", "disability", "unsubscribe",
                    "privacy", "gdpr", "dsar", "abuse", "security", "noreply", "no-reply",
                    "support", "assistance", "helpdesk", "billing", "sales")):
                continue
            if low not in [f.lower() for f in found]:
                found.append(m)
    return found[:5]


def normalise(
    *,
    source: str,
    title: str,
    company: str,
    url: str,
    description: str = "",
    location: str = "",
    tags=None,
    salary: str = "",
    posted_at: str = "",
    contract_hint: str = "",
    apply_email: str = "",
) -> dict:
    title = (title or "").strip()
    company = (company or "").strip() or "Unknown"
    desc = strip_html(description)
    emails = [apply_email] if apply_email else []
    emails += [e for e in find_emails(desc) if e not in emails]
    uid = hashlib.sha1(f"{source}|{company.lower()}|{title.lower()}|{url}".encode()).hexdigest()[:16]
    return {
        "id": uid,
        "source": source,
        "title": title,
        "company": company,
        "location": (location or "").strip(),
        "url": url,
        "description": desc[:12000],
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()][:25],
        "salary": (salary or "").strip(),
        "employment_type": (contract_hint or "").strip(),
        "posted_at": posted_at or "",
        "contact_emails": emails,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------

def remotive() -> list[dict]:
    out = []
    for cat in ("software-dev", "devops"):
        data = _json(f"https://remotive.com/api/remote-jobs?category={cat}&limit=200")
        for j in data.get("jobs", []):
            out.append(normalise(
                source="remotive",
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url", ""),
                description=j.get("description", ""),
                location=j.get("candidate_required_location", "Remote"),
                tags=j.get("tags", []),
                salary=j.get("salary", ""),
                posted_at=j.get("publication_date", ""),
                contract_hint=j.get("job_type", ""),
            ))
    return out


def remoteok() -> list[dict]:
    data = _json("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        sal = ""
        if j.get("salary_min"):
            sal = f"${j.get('salary_min')} - ${j.get('salary_max')}"
        out.append(normalise(
            source="remoteok",
            title=j.get("position", ""),
            company=j.get("company", ""),
            url=j.get("url") or f"https://remoteok.com/l/{j.get('id')}",
            description=j.get("description", ""),
            location=j.get("location", "Remote"),
            tags=j.get("tags", []),
            salary=sal,
            posted_at=j.get("date", ""),
        ))
    return out


def arbeitnow() -> list[dict]:
    """Strong coverage of Austria / Germany / DACH, including English-language roles."""
    out = []
    for page in (1, 2, 3):
        data = _json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        jobs = data.get("data", [])
        if not jobs:
            break
        for j in jobs:
            out.append(normalise(
                source="arbeitnow",
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url", ""),
                description=j.get("description", ""),
                location=j.get("location", ""),
                tags=(j.get("tags") or []) + (j.get("job_types") or []),
                posted_at=datetime.fromtimestamp(j["created_at"], timezone.utc).isoformat()
                if j.get("created_at") else "",
                contract_hint="remote" if j.get("remote") else "",
            ))
    return out


def jobicy() -> list[dict]:
    data = _json("https://jobicy.com/api/v2/remote-jobs?count=100&industry=engineering")
    out = []
    for j in data.get("jobs", []):
        out.append(normalise(
            source="jobicy",
            title=j.get("jobTitle", ""),
            company=j.get("companyName", ""),
            url=j.get("url", ""),
            description=j.get("jobDescription") or j.get("jobExcerpt", ""),
            location=j.get("jobGeo", "Remote"),
            tags=j.get("jobIndustry", []) or [],
            salary=str(j.get("annualSalaryMin") or "") and
            f"{j.get('salaryCurrency','')} {j.get('annualSalaryMin')}-{j.get('annualSalaryMax')}",
            posted_at=j.get("pubDate", ""),
            contract_hint=",".join(j.get("jobType", []) or []),
        ))
    return out


def himalayas() -> list[dict]:
    data = _json("https://himalayas.app/jobs/api?limit=100")
    out = []
    for j in data.get("jobs", []):
        out.append(normalise(
            source="himalayas",
            title=j.get("title", ""),
            company=j.get("companyName", ""),
            url=j.get("applicationLink") or j.get("guid", ""),
            description=j.get("description", ""),
            location=", ".join(j.get("locationRestrictions") or []) or "Remote",
            tags=j.get("categories", []) or [],
            salary=f"{j.get('minSalary','')}-{j.get('maxSalary','')}" if j.get("minSalary") else "",
            posted_at=datetime.fromtimestamp(j["pubDate"], timezone.utc).isoformat()
            if isinstance(j.get("pubDate"), (int, float)) else "",
        ))
    return out


def weworkremotely() -> list[dict]:
    out = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]
    for feed in feeds:
        try:
            root = ET.fromstring(_get(feed))
        except Exception as e:  # noqa: BLE001
            log(f"weworkremotely feed failed {feed}: {e}")
            continue
        for item in root.iter("item"):
            def tx(tag):
                el = item.find(tag)
                return el.text if el is not None and el.text else ""
            raw_title = tx("title")
            company, _, title = raw_title.partition(":")
            out.append(normalise(
                source="weworkremotely",
                title=(title or raw_title).strip(),
                company=company.strip() if title else "",
                url=tx("link"),
                description=tx("description"),
                location=tx("region") or "Remote",
                posted_at=tx("pubDate"),
            ))
    return out


def hn_hiring(months_back: int = 2) -> list[dict]:
    """Hacker News 'Who is hiring?' and 'Freelancer? Seeking freelancer?' threads.

    These are the best source of contract work with a direct email address in the post.

    The threads are found via `search_by_date` restricted to the `whoishiring` account,
    which posts them monthly. A plain `search` sorts by RELEVANCE, not date, and happily
    returns the 2014 and 2016 threads - the first version of this did exactly that, and
    every HN result was five years stale.

    Only "seeking freelancer" is kept from the freelance thread; "seeking work" posts are
    other developers advertising themselves, and they score well precisely because they
    list the same stack.
    """
    out = []
    try:
        search = _json(
            "https://hn.algolia.com/api/v1/search_by_date?"
            + urllib.parse.urlencode({"tags": "story,author_whoishiring", "hitsPerPage": 12})
        )
    except Exception as e:  # noqa: BLE001
        log(f"hn search failed: {e}")
        return out

    wanted = []
    for story in search.get("hits", []):
        title = (story.get("title") or "").lower()
        if "who is hiring" in title or "freelancer" in title:
            wanted.append(story)
        if len(wanted) >= max(2, months_back * 2):
            break
    if not wanted:
        log("hn: no recent hiring threads found")
        return out

    for story in wanted:
        sid = story.get("objectID")
        if not sid:
            continue
        log(f"hn thread: {story.get('title')} ({story.get('created_at', '')[:10]})")
        try:
            thread = _json(f"https://hn.algolia.com/api/v1/items/{sid}")
        except Exception as e:  # noqa: BLE001
            log(f"hn thread {sid} failed: {e}")
            continue
        freelance = "freelancer" in (story.get("title") or "").lower()
        for c in thread.get("children", []) or []:
            text = strip_html(c.get("text") or "")
            if len(text) < 80:
                continue
            first = text.split("\n")[0][:180]
            head = first.upper().replace("*", "").strip()
            if head.startswith("SEEKING WORK") or head.startswith("WANTED:"):
                continue    # another freelancer advertising, not someone hiring
            company = first.split("|")[0].strip()[:80] or "HN poster"
            out.append(normalise(
                source="hn-hiring",
                title=first,
                company=company,
                url=f"https://news.ycombinator.com/item?id={c.get('id')}",
                description=text,
                location="See post",
                posted_at=c.get("created_at", ""),
                contract_hint="freelance" if freelance else "",
            ))
    return out


def adzuna(app_id: str, app_key: str) -> list[dict]:
    """Adzuna - free API key, and the best coverage of Austrian and German roles.

    Register at https://developer.adzuna.com/ and add ADZUNA_APP_ID /
    ADZUNA_APP_KEY as GitHub Actions secrets. Skipped when unset.
    """
    out = []
    countries = ["at", "de", "gb"]
    for c in countries:
        for what in ["react developer", "full stack developer", "node.js developer"]:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/{c}/search/1?"
                + urllib.parse.urlencode({
                    "app_id": app_id, "app_key": app_key,
                    "results_per_page": 50, "what": what,
                    "content-type": "application/json",
                })
            )
            try:
                data = _json(url)
            except Exception as e:  # noqa: BLE001
                log(f"adzuna {c}/{what} failed: {e}")
                continue
            for j in data.get("results", []):
                sal = ""
                if j.get("salary_min"):
                    sal = f"{int(j['salary_min'])}-{int(j.get('salary_max') or j['salary_min'])} {c.upper()}"
                out.append(normalise(
                    source=f"adzuna-{c}",
                    title=j.get("title", ""),
                    company=(j.get("company") or {}).get("display_name", ""),
                    url=j.get("redirect_url", ""),
                    description=j.get("description", ""),
                    location=(j.get("location") or {}).get("display_name", ""),
                    tags=[(j.get("category") or {}).get("label", "")],
                    salary=sal,
                    posted_at=j.get("created", ""),
                    contract_hint=j.get("contract_type", "") or j.get("contract_time", ""),
                ))
    return out


ADAPTERS = {
    "remotive": remotive,
    "remoteok": remoteok,
    "arbeitnow": arbeitnow,
    "jobicy": jobicy,
    "himalayas": himalayas,
    "weworkremotely": weworkremotely,
    "hn-hiring": hn_hiring,
}
