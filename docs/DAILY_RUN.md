# Daily run — runbook

This is what the scheduled weekday Claude session does. It is the only step with
judgement in it; everything around it is deterministic code.

Repo: `saifaslam246/jobs`, branch `claude/job-portal-cv-manager-7w6cxz`.
Portal: <https://claude.ai/code/artifact/de2e9c98-4ec2-443d-937f-6949e3efb79a>

Timing on a weekday, all UTC:

| 05:30 | GitHub Action harvests and scores, commits `data/` |
| 06:30 | this run: sync, draft, tailor |
| 08:10 | GitHub Action sends whatever Saif approved |

## 1. Sync approvals out of the portal — do this first

Read `outbox/*` from the artifact database. For every document whose `status` is
`approved` but whose queue file in `outreach/queue/` still says `draft`, set the queue
file to `approved` and stamp `approved_at`. For `skipped`, set the queue file to
`skipped`. Commit and push — the send workflow reads the repo, not the database, so an
approval that is not synced never goes out.

Also read `pipeline/*` and carry any status Saif set into `data/applications.json`.

## 2. Pull the new harvest

`git pull`. Read `data/digest.md` and `data/last-run.json`. If a source failed two runs
running, say so in the summary — a silently dead source is the main way this pipeline
rots.

## 3. Pick the day's targets

From `data/matches.json`, take roles where `match.verdict == "shortlist"` and
`status == "new"`. Cap at **6 a day**. Prefer, in order:

1. a direct contact email in the posting
2. contract, freelance, part-time or project-based
3. posted in the last 48 hours
4. higher score

Volume is not the goal. Six well-aimed applications beat sixty generic ones, and the
send cap is 10 a day regardless.

## 4. Read each posting properly

Open the description in `matches.json`. Do not apply from the title. Check:

- Is the primary stack actually his? The scorer gates on this but is not infallible.
- Any eligibility blocker — visa sponsorship, region lock, onsite-only, clearance. If
  it blocks him, mark the job `dismissed` and move on.
- What is the single most specific requirement he genuinely matches? That sentence is
  what the email is built around.

## 5. Tailor the CV

```bash
python profile/cv/build_cv.py --job <job_id> --title "<their exact job title>"
```

Pick `--variant` by role: `frontend`, `mobile` (React Native / Flutter), `backend`,
`data_scraping` (crawling / ETL), else `fullstack`. Check `match.gaps` — if the posting
wants something real that he has and the CV does not say, add it to
`profile/master-profile.json` and rebuild. **Never add a skill he does not have.**

## 6. Draft the email

Use `outreach/templates.md` and obey the sending rules in it. One JSON per email in
`outreach/queue/`, `status: "draft"`, attaching the CV built in step 5.

Each email must name something specific about *their* product and quote the requirement
from step 4. A draft that could have been sent to any company is a failed draft — delete
it rather than queue it.

Only write to a `jobs@`/`careers@` address on the company's own domain, or a person who
published their address in the posting. Never guess an address.

## 7. Push everything to the portal

Write new jobs to the `jobs` collection and new drafts to the `outbox` collection in the
artifact database. Keep `jobs` to the top ~100 by score; delete lower-scoring documents
that Saif has no status on, so the 5,000-document cap stays far away.

Never write to `pipeline/*` — that collection is Saif's.

## 8. Commit, push, report

One commit. Then tell Saif, briefly: how many new shortlisted roles, how many drafts are
waiting for approval, anything that needs a decision, and anything that broke. If there
is nothing to approve and nothing broke, say exactly that — do not pad it.
