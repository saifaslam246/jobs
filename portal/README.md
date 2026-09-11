# Portal

`job-desk.html` is the source of the **Contract Desk** dashboard, published as a private
Claude Artifact at
<https://claude.ai/code/artifact/de2e9c98-4ec2-443d-937f-6949e3efb79a>.

## How data reaches it

The published page cannot fetch from GitHub - the Artifact CSP blocks network requests to
anything outside a small CDN allowlist. So the page reads from its own artifact database
instead, and Claude writes into it:

```
GitHub Action commits data/matches.json
        |
Claude session reads it, writes each job to  jobs/<job_id>
        |
page renders it; you change status -> page writes  pipeline/<job_id>
        |
Claude reads pipeline/* back to see what you have acted on
```

`jobs/*` is Claude-written and refreshed on every harvest. `pipeline/*` is yours - status
and notes - and is never overwritten by a refresh. Keeping them in separate collections is
what makes that guarantee hold.

## Republishing

Edit this file, then republish it to the **same URL** (pass the URL as `url` if you are in
a different conversation). Publishing without the URL creates a second, unrelated artifact.
