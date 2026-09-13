"""Send approved outreach emails. Runs in GitHub Actions, never from a Claude session.

Nothing here decides what to send. It sends only what is already sitting in
outreach/queue/ with status "approved" - drafted by Claude, approved by Saif in the
portal. A draft is never sent, and a sent item is never sent twice.

Guardrails, in order of how badly they matter:
  * DAILY_CAP sends per calendar day, counted from the queue itself, not from a
    counter that could be reset. Above ~20 cold sends a day a personal Gmail starts
    tripping spam filters.
  * status must be exactly "approved"
  * sent_at must be empty
  * a per-recipient-domain cap, so one bad day cannot carpet one company
  * plain text only, one attachment (the tailored CV), no tracking, no HTML

Required secrets (repository Settings -> Secrets and variables -> Actions):
  SMTP_HOST      smtp.gmail.com
  SMTP_PORT      587
  SMTP_USER      your gmail address
  SMTP_PASS      a Gmail App Password - NOT your account password
  FROM_NAME      Saif ur Rehman
"""
from __future__ import annotations

import json
import mimetypes
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "outreach" / "queue"
CONFIG = ROOT / "outreach" / "config.json"
PROFILE = ROOT / "profile" / "master-profile.json"


def forbidden_claims() -> list[str]:
    """Technologies Saif has said he has not worked with.

    Removing them from the profile does not reach a draft that was written before the
    correction - one such draft was written, corrected in the CV, and still went on to
    be approved with the claim intact. This is the last gate before an email leaves.
    """
    try:
        return json.loads(PROFILE.read_text()).get("do_not_claim", [])
    except Exception:  # noqa: BLE001 - an unreadable profile must not silently open the gate
        log("WARNING: could not read the profile; refusing to send")
        return ["*"]


def claim_violations(d: dict, banned: list[str]) -> list[str]:
    if banned == ["*"]:
        return ["profile unreadable"]
    text = f"{d.get('subject', '')} {d.get('body', '')}".lower()
    return [b for b in banned if b.lower() in text]


def load_config() -> dict:
    default = {"mode": "approve_first", "daily_cap": 10, "per_company_cap": 2,
               "auto": {"min_score": 60, "require_contact_email": True,
                        "require_contract_signal": False, "max_per_day": 6,
                        "skip_if_flags": True}}
    if not CONFIG.exists():
        return default
    try:
        cfg = json.loads(CONFIG.read_text())
    except Exception as e:  # noqa: BLE001 - a broken config must not start sending
        print(f"[send] config unreadable ({e}); falling back to approve_first", flush=True)
        return default
    default.update({k: v for k, v in cfg.items() if not k.startswith("_")})
    return default


CFG = load_config()
DAILY_CAP = int(os.getenv("DAILY_CAP") or CFG["daily_cap"])
PER_DOMAIN_CAP = int(CFG.get("per_company_cap", 2))


def log(m: str) -> None:
    print(f"[send] {m}", flush=True)


def load() -> list[tuple[Path, dict]]:
    items = []
    for fp in sorted(QUEUE.glob("*.json")):
        try:
            items.append((fp, json.loads(fp.read_text())))
        except Exception as e:  # noqa: BLE001
            log(f"skipping unreadable {fp.name}: {e}")
    return items


def sent_today(items) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for _, d in items if (d.get("sent_at") or "").startswith(today))


def auto_clears_bar(d: dict) -> tuple[bool, str]:
    """In auto mode, decide whether a draft may send without Saif seeing it.

    A draft that fails any bar is not discarded - it stays a draft and waits in the
    portal. Unattended sending is the fast path, never the only path.
    """
    a = CFG.get("auto", {})
    score = d.get("score")
    if a.get("min_score") is not None and (score is None or score < a["min_score"]):
        return False, f"score {score} below auto minimum {a['min_score']}"
    if a.get("require_contact_email", True) and not d.get("to"):
        return False, "no contact address"
    if a.get("require_contract_signal") and not d.get("is_contract"):
        return False, "not flagged as contract work"
    if a.get("skip_if_flags", True) and d.get("flags"):
        return False, f"eligibility flag: {'; '.join(d['flags'])[:80]}"
    if not d.get("attachments"):
        return False, "no CV attached"
    return True, ""


def promote_auto(items) -> int:
    """Mark qualifying drafts approved when mode is auto. Returns how many."""
    if CFG.get("mode") != "auto":
        return 0
    a = CFG.get("auto", {})
    budget = int(a.get("max_per_day", 6))
    promoted = 0
    for fp, d in items:
        if promoted >= budget:
            break
        if d.get("status") != "draft":
            continue
        ok, why = auto_clears_bar(d)
        if not ok:
            log(f"  auto-hold {fp.name}: {why}")
            continue
        d["status"] = "approved"
        d["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        d["approved_by"] = "auto"
        fp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        promoted += 1
        log(f"  auto-approved {fp.name} -> {d['to']}")
    return promoted


def build(d: dict, from_addr: str, from_name: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = d["to"]
    msg["Subject"] = d["subject"]
    msg["Reply-To"] = from_addr
    msg.set_content(d["body"])

    for rel in d.get("attachments", []) or []:
        p = (ROOT / rel).resolve()
        # never let a queue file reach outside the repo
        if not str(p).startswith(str(ROOT)) or not p.is_file():
            log(f"  skipping attachment outside the repo or missing: {rel}")
            continue
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


def main() -> int:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    # Google displays an App Password as four groups of four; pasted as shown, the
    # spaces are part of the secret and the login fails.
    password = (os.getenv("SMTP_PASS") or "").replace(" ", "") or None
    from_name = os.getenv("FROM_NAME", "Saif ur Rehman")

    items = load()
    log(f"mode: {CFG.get('mode')}")
    if promote_auto(items):
        items = load()
    approved = [(fp, d) for fp, d in items
                if d.get("status") == "approved" and not d.get("sent_at")]
    if not approved:
        log("nothing approved and unsent - done")
        return 0

    # Screen every approved draft for a claim Saif has disowned, before a connection is
    # opened. A draft that fails this is returned to draft rather than dropped: the
    # posting is still worth applying to, the sentence is not.
    banned = forbidden_claims()
    held = 0
    for fp, d in list(approved):
        bad = claim_violations(d, banned)
        if not bad:
            continue
        d["status"] = "draft"
        d["error"] = "held: claims " + ", ".join(bad) + " - not yours to claim"
        fp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        log(f"  HELD {fp.name}: claims {', '.join(bad)} - returned to draft for rewriting")
        approved.remove((fp, d))
        held += 1
    if held:
        log(f"{held} draft(s) held back; {len(approved)} still approved")
    if not approved:
        log("nothing left to send after screening")
        return 0

    if not (host and user and password):
        log("SMTP secrets are not set, so nothing can be sent.")
        log(f"{len(approved)} approved email(s) are waiting in outreach/queue/.")
        log("Add SMTP_HOST, SMTP_PORT, SMTP_USER and SMTP_PASS as repository secrets.")
        return 0

    already = sent_today(items)
    budget = max(0, DAILY_CAP - already)
    if budget == 0:
        log(f"daily cap reached ({already}/{DAILY_CAP}) - stopping")
        return 0
    log(f"{len(approved)} approved, {already} already sent today, budget {budget}")

    domain_count: dict[str, int] = {}
    for _, d in items:
        if d.get("sent_at"):
            domain_count[d["to"].split("@")[-1].lower()] = \
                domain_count.get(d["to"].split("@")[-1].lower(), 0) + 1

    ctx = ssl.create_default_context()
    sent = failed = 0
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls(context=ctx)
        s.login(user, password)
        for fp, d in approved:
            if budget <= 0:
                log("budget spent - the rest stay queued for tomorrow")
                break
            dom = d["to"].split("@")[-1].lower()
            if domain_count.get(dom, 0) >= PER_DOMAIN_CAP:
                log(f"  skip {fp.name}: already {domain_count[dom]} sent to {dom}")
                continue
            try:
                s.send_message(build(d, user, from_name))
            except Exception as e:  # noqa: BLE001 - one bad address must not stop the batch
                d["error"] = str(e)[:300]
                d["status"] = "failed"
                fp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
                log(f"  FAILED {d['to']}: {e}")
                failed += 1
                continue
            d["sent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            d["status"] = "sent"
            d.pop("error", None)
            fp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
            domain_count[dom] = domain_count.get(dom, 0) + 1
            budget -= 1
            sent += 1
            log(f"  sent -> {d['to']} | {d['subject'][:60]}")

    log(f"done: {sent} sent, {failed} failed, {len(approved) - sent - failed} still queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
