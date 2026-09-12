# Outreach queue

One JSON file per email. Claude writes drafts here; you approve them in the portal;
`outreach/send.py` sends only what is approved, from GitHub Actions.

```json
{
  "id": "2026-09-12-acme-react-dev",
  "job_id": "f483bb3b92bdaaaa",
  "to": "jobs@acme.com",
  "subject": "React Developer - 4 yrs React/Node, available immediately",
  "body": "Hi ...\n\nplain text only\n",
  "attachments": ["profile/cv/generated/Saif_ur_Rehman_CV_acme_react-developer.pdf"],
  "status": "draft",
  "created_at": "2026-09-12T09:40:00+00:00",
  "approved_at": null,
  "sent_at": null
}
```

`status` moves `draft` -> `approved` -> `sent`, or `failed`. Only `approved` is ever
sent, `sent_at` is the guard against a double send, and attachment paths must stay
inside the repository.
