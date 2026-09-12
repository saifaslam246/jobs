# How it works

Plain guide to the whole system: where the jobs live, what runs without you, and what
happens when you close Claude.

---

## The short answer

**Yes — it keeps running when Claude is closed.** Nothing in the daily loop depends on
you or on a chat window being open. Three things run on their own:

| What | Where it runs | When |
|---|---|---|
| Harvest jobs, score them | GitHub Actions | every day, 05:30 UTC |
| Draft CVs and emails, update the portal | a scheduled Claude session | weekdays, 06:30 UTC |
| Send what you approved | GitHub Actions | weekdays, 08:10 UTC |

You open the portal whenever you like — on your phone, on your laptop, a week later.
It is a saved web page with its own database, not a chat.

---

## Where the jobs actually live

They live in **two places**, on purpose.

**1. In the repo** — `data/matches.json` on GitHub. This is the full record: every
scored role, its description, its match reasons. Permanent, versioned, and what the
automation reads. Roughly 1,200 relevant roles after each harvest.

**2. In the portal's database** — the top ~100 by score, plus your status on each. This
is what the page you look at reads from. It is attached to the artifact itself, so it
survives you closing the tab, closing Claude, restarting your Mac, and switching
devices.

The repo is the archive; the portal is the working surface.

---

## What runs without you

### 05:30 UTC — the harvest (GitHub Actions)

A workflow on GitHub's servers wakes up, calls 8 job sources, scores every posting
against `profile/master-profile.json`, and commits the results. It does not need your
computer on, and it does not need Claude.

You can watch it: **github.com/saifaslam246/jobs → Actions → Daily job harvest**. Green
tick means it ran. Click a run to see the digest of what it found.

### 06:30 UTC weekdays — the Claude run

A scheduled Claude session starts by itself, reads the overnight harvest, picks up to 6
targets, builds a CV tailored to each one, writes the emails, and pushes everything into
the portal. Then it shuts down. You get a phone notification when it finishes.

This is the only step with judgement in it. It follows `docs/DAILY_RUN.md`.

### 08:10 UTC weekdays — the send

A workflow sends only the emails you marked **approved** in the portal. Never a draft.
Never twice. Maximum 10 a day and 2 per company.

---

## What you do

About five minutes, once a day:

1. Open the portal. New roles are at the top, best match first.
2. Open anything interesting. You get the full posting, why it scored, what the CV needs
   to cover, and the contact email if the posting had one.
3. Set a status — Shortlisted, Applied, Dismissed. This is how the system learns what
   you have already handled and stops showing it to you.
4. Go to the **Outbox** tab. Read each draft. **Approve & queue** sends it next morning;
   **Skip this one** drops it.

That's it. You never have to search a job board again.

---

## Opening the portal

Bookmark this: <https://claude.ai/code/artifact/de2e9c98-4ec2-443d-937f-6949e3efb79a>

It works on any device you are signed into claude.ai with. It is private — only you can
open it unless you deliberately share it.

The first time you open it, the page asks permission to read its own database. **Say
yes** — without it the page loads but stays empty, which is exactly what an empty
Pipeline tab means. There is a status strip under the tabs that tells you which state
you are in:

- **green** — connected, showing the live list, your changes are saved
- **amber** — needs permission, or you are looking at an offline snapshot
- **red** — cannot reach the database; there is a Reconnect button

### The snapshot file is different

`portal/snapshot.html` is a frozen copy with the jobs baked in. Useful for showing
someone without giving them access, or for looking offline. It is **not** connected to
anything: status changes stay in that one browser and never reach the portal, and it
never updates. The status strip says so in amber.

---

## If something looks wrong

**Portal is empty.** Check the status strip. Amber with an "Allow access" button means
you have not granted the database permission yet — click it.

**No new jobs for days.** Check Actions on GitHub. If the harvest is red, open the run
and read the log. If a single source failed, the others still ran — the digest names
which one broke.

**Emails are not sending.** The Gmail App Password secret is almost certainly missing.
The send workflow reports "SMTP secrets are not set" and exits without sending, so your
approved drafts stay queued rather than getting lost. Add the secrets and they go out on
the next run.

**A bad job keeps appearing.** Mark it Dismissed. To fix the underlying cause, the
scoring rules are in `profile/master-profile.json` under `matching` — or just tell
Claude which roles are wrong and why.
