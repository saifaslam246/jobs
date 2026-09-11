# Job & contract pipeline

An automated pipeline that harvests developer jobs and contracts daily, scores them
against one master profile, generates a tailored ATS-safe CV per role, and drafts the
outreach. Built for Saif ur Rehman - full-stack developer, Austria.

## Why it is built this way

The Claude session container's egress policy allows GitHub and package registries only
- every job API is blocked from there. So **fetching runs in GitHub Actions** (which has
unrestricted internet), commits its results into `data/`, and Claude reads them from the
repo. That split is not a workaround; it is also cheaper, survives container restarts,
and gives every run an auditable commit.

```
GitHub Actions (daily 05:30 UTC)
   pipeline/fetch.py  ->  8 job sources
   pipeline/score.py  ->  ranked against profile/master-profile.json
   commit data/matches.json + data/digest.md
        |
        v
Claude session reads data/  ->  tailors CV per role  ->  drafts outreach
        |
        v
Artifact dashboard (pipeline state, persists your status changes)
```

## Layout

| Path | What it is |
|---|---|
| `profile/master-profile.json` | **Single source of truth.** Every CV, score and letter derives from this. Edit here only. |
| `profile/cv/build_cv.py` | ATS-safe CV generator - DOCX + PDF + TXT |
| `profile/cv/generated/` | Built CVs (master + one per application) |
| `pipeline/sources.py` | One adapter per job board |
| `pipeline/score.py` | Explainable match scoring |
| `pipeline/fetch.py` | Daily entrypoint; merges new results with your existing pipeline state |
| `data/matches.json` | Ranked jobs + your status on each |
| `data/digest.md` | Human-readable daily digest |
| `outreach/templates.md` | Email templates + the deliverability rules that keep them out of spam |
| `.github/workflows/daily-jobs.yml` | The scheduled harvest |

## Sources

Free and without an API key: **Remotive**, **RemoteOK**, **Arbeitnow** (strong DACH /
Austria coverage), **Jobicy**, **Himalayas**, **WeWorkRemotely**, and **Hacker News**
"Who is hiring" + "Freelancer? Seeking freelancer?" threads - the last of these is the
best source of contract work with a direct email address in the post.

With a free key: **Adzuna** (the best Austrian and German coverage). Register at
<https://developer.adzuna.com/>, then add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` as
repository secrets under Settings -> Secrets and variables -> Actions. The pipeline
skips Adzuna silently when the secrets are absent.

### Not included, deliberately

**LinkedIn, Indeed, Glassdoor and Upwork have no usable public job API.** The only way
to pull them is to drive a logged-in session with your own cookie, which violates their
terms and gets accounts restricted or permanently banned. Your LinkedIn is an asset in a
job search, so it stays manual: the pipeline covers everything it legitimately can, and
LinkedIn Easy Apply stays a five-minute daily job for you.

## Running it

```bash
# manually, anywhere with internet
python pipeline/fetch.py

# build the master CV
python profile/cv/build_cv.py

# build a variant
python profile/cv/build_cv.py --variant mobile

# build a CV tailored to one scored job
python profile/cv/build_cv.py --job <job_id> --title "React Developer"
```

The Action also runs on demand: Actions tab -> "Daily job harvest" -> Run workflow.

> The cron only fires once this branch is merged into the repository's default branch -
> GitHub schedules workflows from the default branch only. Until then, use Run workflow.

## Scoring

`pipeline/score.py` gates on stack overlap, then rejects wrong-primary-stack and
out-of-range seniority, then scores on: stack match (max 50), role shape (15),
contract/part-time signal (12), location and remote fit (12), familiar domain (8),
actionability - a direct contact email in the post (8), and freshness (10, negative past
60 days). Anything at 55+ lands on the shortlist.

Every job carries its `match.reasons`, so a bad ranking is traceable and the weights are
fixable. Eligibility problems (visa, clearance, onsite-only) are **flags to check**, not
silent rejects.
