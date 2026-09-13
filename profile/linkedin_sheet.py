"""Generate the LinkedIn paste sheet from the master profile.

LinkedIn has no API for editing a profile - the only programmatic route is driving a
logged-in browser session, which breaches their terms and gets accounts restricted. So
this does the next best thing: every field LinkedIn asks for, pre-written from the same
profile the CV comes from, one click from the clipboard.

Same source as the CV, so the two cannot say different things.

    python profile/linkedin_sheet.py > portal/linkedin.html
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile" / "master-profile.json"

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# LinkedIn's own limits, so you find out here rather than when it truncates you.
LIMITS = {"headline": 220, "about": 2600, "role": 2000, "skills": 50}


def fmt(v, current=False):
    if current or not v:
        return "Present"
    y, _, m = v.partition("-")
    return f"{MONTHS[int(m)]} {y}" if m else y


def blocks(d: dict) -> list[dict]:
    ident = d["identity"]
    out = [
        {"field": "Headline", "where": "Profile → pencil icon → Headline",
         "limit": LIMITS["headline"], "text": ident["headline"]},
        {"field": "About", "where": "Profile → About → pencil icon",
         "limit": LIMITS["about"], "text": d["summary"]},
    ]
    for e in d["experience"]:
        body = "\n".join("• " + b for b in e["bullets"])
        if e.get("stack"):
            body += "\n\nTechnologies: " + ", ".join(e["stack"])
        out.append({
            "field": f"Experience — {e['company']}",
            "where": "Profile → Experience → + → fill the fields below",
            "limit": LIMITS["role"], "text": body,
            "meta": [("Title", e["title"]), ("Company", e["company"]),
                     ("Location", e["location"]),
                     ("Start", fmt(e["start"])),
                     ("End", fmt(e.get("end"), e.get("current", False)))],
        })
    for ed in d["education"]:
        out.append({
            "field": f"Education — {ed['institution']}",
            "where": "Profile → Education → +", "limit": 0, "text": "",
            "meta": [("School", ed["institution"]), ("Degree", ed["degree"]),
                     ("From", str(ed["start"])),
                     ("To", str(ed.get("end") or ed.get("status", "")))],
        })

    for pr in sorted(d.get("linkedin_projects", []), key=lambda x: x["priority"]):
        if not pr["description"]:
            out.append({
                "field": f"Project — {pr['name']}", "where": "Profile → Projects → +",
                "limit": 0, "text": "",
                "note": f"Not written yet. Tell Claude {pr['needs']} and this fills in.",
            })
            continue
        meta = [("Project name", pr["name"]),
                ("Dates", pr["dates"] or "NEEDS YOUR DATES"),
                ("Associated with", pr["association"])]
        out.append({
            "field": f"Project — {pr['name'].split(' -')[0]}",
            "where": "Profile → Projects → + → fill the fields below",
            "limit": LIMITS["role"], "text": pr["description"], "meta": meta,
            "note": (f"Skills to tag: {pr['skills']}"
                     + (f"  ·  Still needs {pr['needs']}." if pr.get("needs") else "")),
        })

    seen, skills = set(), []
    for cat in ("Frontend", "Backend", "Databases", "Programming Languages",
                "Cloud and DevOps", "Mobile", "Integrations and Testing"):
        for s in d["skills"].get(cat, []):
            if s.lower() not in seen:
                seen.add(s.lower())
                skills.append(s)
    out.append({
        "field": "Skills", "where": "Profile → Skills → + → add one at a time",
        "limit": LIMITS["skills"], "unit": "skills",
        "text": "\n".join(skills[:LIMITS["skills"]]),
        "note": f"{len(skills)} in your profile, LinkedIn caps at {LIMITS['skills']} - "
                "the most relevant are listed, in the order worth adding them.",
    })
    return out


def render(d: dict) -> str:
    e = html.escape
    parts = []
    for i, b in enumerate(blocks(d)):
        # Skills are capped by COUNT, every other field by characters. Measuring skills
        # in characters put a false "over limit" badge on a list that was within it.
        if b.get("unit") == "skills":
            n = len([x for x in b["text"].split("\n") if x.strip()])
            unit = " skills"
        else:
            n = len(b["text"])
            unit = ""
        over = b["limit"] and n > b["limit"]
        counter = (f'<span class="count {"over" if over else ""}">{n} / {b["limit"]}{unit}</span>'
                   if b["limit"] else "")
        meta = ""
        if b.get("meta"):
            meta = '<dl class="meta">' + "".join(
                f'<dt>{e(k)}</dt><dd><code>{e(v)}</code>'
                f'<button class="mini" data-copy="m{i}-{j}">copy</button>'
                f'<span hidden id="m{i}-{j}">{e(v)}</span></dd>'
                for j, (k, v) in enumerate(b["meta"])) + "</dl>"
        body = ""
        if b["text"]:
            body = (f'<pre id="t{i}">{e(b["text"])}</pre>'
                    f'<button class="copy" data-copy="t{i}">Copy this</button>')
        note = f'<p class="note">{e(b["note"])}</p>' if b.get("note") else ""
        parts.append(
            f'<section><header><h2>{e(b["field"])}</h2>{counter}</header>'
            f'<p class="where">{e(b["where"])}</p>{meta}{body}{note}</section>')
    return "\n".join(parts)


if __name__ == "__main__":
    d = json.loads(PROFILE.read_text())
    tpl = (ROOT / "portal" / "linkedin_template.html").read_text()
    print(tpl.replace("<!--BLOCKS-->", render(d)))
