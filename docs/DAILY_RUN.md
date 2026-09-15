# Daily run — runbook

This is what the scheduled weekday Claude session does. It is the only step with
judgement in it; everything around it is deterministic code.

Repo: `saifaslam246/jobs`, branch `claude/job-portal-cv-manager-7w6cxz`.
Portal: <https://claude.ai/code/artifact/de2e9c98-4ec2-443d-937f-6949e3efb79a>

Timing on a weekday, all UTC:

| 05:30 | GitHub Action harvests and scores, commits `data/` |
| 06:30 | this run: sync, draft, tailor |
| 06:10-10:10 | GitHub Action tries hourly to send whatever Saif approved |

## 0. Attach the repository — before anything else

Each firing of the Routine starts a new session with no repository authorized, so a
push is refused with *"not in this session's authorized repository set"* and the whole
run's work is lost. Call `add_repo` for `saifaslam246/jobs` with `access: "push"`, run
the clone command it returns, then `register_repo_root`. If it fails, stop and report
that - do not draft work that cannot be saved.

At the end, confirm the push actually landed. `git status` must say the branch is up to
date with origin and `git log origin/<branch> -1` must show the run's commit. A run that
could not push has not succeeded, whatever else it did.

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

Cap at **6 a day**, filled in this order:

1. **Anything Saif marked `shortlisted`.** He picked it by hand, which outranks any
   score this pipeline produced. These come first, every time, until they are done.
2. Then roles where `match.verdict == "shortlist"` and `status == "new"`.

Within each group prefer, in order:

- a direct contact email in the posting
- contract, freelance, part-time or project-based
- posted in the last 48 hours
- higher score

Skip anything already `applied`, `replied`, `interview`, `rejected` or `dismissed` -
those are closed as far as this run is concerned.

When a tailored CV has been built for a role, set its status to `cv_ready` so the portal
shows it is ready to go out. Never set any other status: the rest are Saif's.

Volume is not the goal. Six well-aimed applications beat sixty generic ones, and the
send cap is 10 a day regardless.

## 4. Read each posting properly

Open the description in `matches.json`. Do not apply from the title. Check:

- Is the primary stack actually his? The scorer gates on this but is not infallible.
- Any eligibility blocker — visa sponsorship, region lock, onsite-only, clearance. If
  it blocks him, mark the job `dismissed` and move on.
- What is the single most specific requirement he genuinely matches? That sentence is
  what the email is built around.

## 5. Attach the CV - his own file by default

**Default: attach `profile/cv/master/Saif_Ur_Rehman.pdf` unchanged.** That is Saif's own
PDF, byte for byte as he wrote it. Do not regenerate it, do not reword it, do not swap in
a build. Most applications get exactly this file.

**Only tailor when the switch is on for that role.** The portal carries a per-job switch,
off by default; turning it on writes `tailor: true` into that role's `pipeline/<job_id>`
document. For those roles only:

```bash
python profile/cv/tailor_switches.py --on <job_id>
python portal/build_cvdata.py
```

That writes `profile/cv/tailored/Saif_ur_Rehman_CV_<job_id>.pdf`, records the switch in
`data/tailor.json`, and leaves `profile/cv/master/` alone. `outreach/send.py` reads
`data/tailor.json` to choose the attachment, so that file is what actually decides which
CV goes out - keep it in step with the `pipeline` collection.

The generator reproduces the master's layout exactly - same fonts, sizes, margins,
section order and wording - so a tailored CV is his document with its skills and projects
reordered around one posting, not a different CV. It **reorders only**. Never rewrite,
add or remove a sentence, and never introduce a technology that is not already in his
profile.

Before relying on a tailored build, confirm the generator has not drifted from his file:

```bash
python profile/cv/build_cv.py && python profile/cv/ats_check.py --compare
```

That must report a 100% word match. If it does not, stop and report it rather than
sending a CV that no longer matches the one he wrote.

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
<!-- weekday run push check: 2026-09-15 -->
