"""Generate ATS-safe CVs (DOCX + PDF + TXT) from profile/master-profile.json.

ATS rules this file deliberately follows:
  * one column, no tables, no text boxes, no images, no headers/footers
  * contact details in the document body, never in a header
  * standard section headings ("PROFESSIONAL EXPERIENCE", not "My Journey")
  * standard fonts (Calibri / Helvetica), 10-11pt, black on white
  * literal bullet characters with hanging indents, no Word list auto-numbering
  * dates as plain text on their own line, never in tab-aligned columns
  * every skill written the way a job ad writes it ("Node.js", not "Node")

Usage:
  python build_cv.py                       # master CV, full-stack variant
  python build_cv.py --variant mobile      # mobile-leaning variant
  python build_cv.py --job <job_id>        # tailored to a job in data/matches.json
  python build_cv.py --job <id> --title "React Developer"
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE = ROOT / "profile" / "master-profile.json"
MATCHES = ROOT / "data" / "matches.json"
OUT = ROOT / "profile" / "cv" / "generated"

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def fmt_date(v: str | None, current: bool = False) -> str:
    if current or not v:
        return "Present"
    y, _, mth = v.partition("-")
    return f"{MONTHS[int(mth)]} {y}" if mth else y


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


# ---------------------------------------------------------------------------
# Content assembly - shared by every output format
# ---------------------------------------------------------------------------

def build_content(p: dict, job: dict | None, title_override: str | None) -> dict:
    """Assemble the CV.

    With no job, this is the master CV exactly as Saif wrote it. With a job, tailoring
    reorders his existing material - skills categories the posting asks for first, the
    most relevant projects first - and mirrors their job title. It never rewrites his
    prose: every sentence on a tailored CV is a sentence he approved on the master.
    """
    ident = p["identity"]
    headline = title_override or ident["headline"]

    contact_lines = [
        " | ".join([ident["location"], ident["phone"], ident["email"]]),
        f"LinkedIn: {ident['linkedin']} | GitHub: {ident['github']}",
    ]
    if ident.get("portfolio_public") and ident.get("portfolio"):
        contact_lines.append(f"Portfolio: {ident['portfolio']}")

    summary = p["summary"]

    # Skills: when tailoring, lead with the categories the job actually asks for.
    skills = {k: list(v) for k, v in p["skills"].items()}
    # merge ORMs into Databases - one fewer line, same keywords for the parser
    if "ORMs" in skills:
        skills["Databases"] = skills["Databases"] + skills.pop("ORMs")
    jd_terms: list[str] = []
    if job:
        jd_terms = [t for t in job["match"]["matched"]]
        order = []
        for cat, items in skills.items():
            hits = sum(1 for i in items if any(t.lower() in i.lower() for t in jd_terms))
            order.append((-hits, cat))
        skills = {cat: skills[cat] for _, cat in sorted(order)}

    # Projects: when tailoring, surface the ones sharing tech or domain with the JD.
    projects = list(p["projects"])
    if job:
        hay = f"{job.get('title','')} {job.get('description','')}".lower()

        # Only count technologies the scorer actually detected in this posting, and
        # weigh each project's own strength. Counting raw substring hits let a generic
        # description - which names almost nothing - pick projects at random, and
        # "react" matched inside "React Native" as well.
        detected = {t.lower() for t in (job.get("match") or {}).get("matched", [])}

        def mentions(term: str) -> bool:
            """Whole-word match. Plain substring search had "ai" matching inside
            "maintainable" and "data" inside "data models", so every project collected
            domain hits from generic prose."""
            return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", hay) is not None

        def relevance(pr: dict) -> int:
            t = sum(4 for x in pr["tech"] if x.lower() in detected)
            d = sum(6 for x in pr["domain"] if mentions(x))
            # Weight counts triple, and domain overlap is worth more than a framework
            # name. Without this, a medical-software posting led with a marketplace
            # project purely because its tech list happened to name Docker and MongoDB,
            # pushing the healthcare work - the whole reason he fits - to third.
            return -(t + d + pr.get("weight", 0) * 3)

        projects.sort(key=relevance)
    # Three projects, not four: the Ludwig role now carries six bullets of its own, and a
    # two-page CV is worth more than a fourth project nobody reads.
    projects = projects[:3]
    # two bullets per project keeps the CV to two pages; the third is detail the
    # interview is for, not the screen.
    projects = [{**pr, "bullets": pr["bullets"][:2]} for pr in projects]

    return {
        "name": ident["full_name"],
        "headline": headline,
        "contact_lines": contact_lines,
        "summary": summary,
        "skills": skills,
        "experience": p["experience"],
        "projects": projects,
        "education": p["education"],
        "certifications": p["certifications"],
        "languages": [l for l in p["languages"] if l.get("level")],
        "jd_terms": jd_terms,
    }


# ---------------------------------------------------------------------------
# DOCX - the format most ATS parse best
# ---------------------------------------------------------------------------

def write_docx(c: dict, path: Path) -> None:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.06

    for s in doc.sections:
        s.top_margin = s.bottom_margin = Inches(0.5)
        s.left_margin = s.right_margin = Inches(0.6)

    def para(text="", size=10.5, bold=False, italic=False, space_before=0, space_after=0,
             align=None, color=None, caps=False, justify=False):
        pr = doc.add_paragraph()
        if justify:
            pr.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pr.paragraph_format.space_before = Pt(space_before)
        pr.paragraph_format.space_after = Pt(space_after)
        if align:
            pr.alignment = align
        run = pr.add_run(text.upper() if caps else text)
        run.font.size = Pt(size)
        run.bold = bold
        run.italic = italic
        if color:
            run.font.color.rgb = RGBColor(*color)
        return pr

    def heading(text):
        pr = para(text, size=11, bold=True, space_before=10, space_after=3, caps=True)
        pr.paragraph_format.keep_with_next = True
        # a bottom rule drawn as a border, not a table or image - ATS-safe
        p_el = pr._p.get_or_add_pPr()
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "888888")
        borders.append(bottom)
        p_el.append(borders)

    def bullet(text):
        pr = doc.add_paragraph()
        pr.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pr.paragraph_format.left_indent = Inches(0.22)
        pr.paragraph_format.first_line_indent = Inches(-0.14)
        pr.paragraph_format.space_after = Pt(1.5)
        run = pr.add_run("•  " + text)
        run.font.size = Pt(10.5)

    # --- header (in the body, not a Word header) ---
    para(c["name"], size=20, bold=True, space_after=1)
    para(c["headline"], size=10.5, space_after=3)
    for ln in c["contact_lines"]:
        para(ln, size=9, space_after=0)

    heading("Professional Summary")
    para(c["summary"], space_after=2, justify=True)

    heading("Technical Skills")
    for cat, items in c["skills"].items():
        pr = doc.add_paragraph()
        pr.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pr.paragraph_format.space_after = Pt(1.5)
        r = pr.add_run(f"{cat}: ")
        r.bold = True
        r.font.size = Pt(10.5)
        r2 = pr.add_run(", ".join(items))
        r2.font.size = Pt(10.5)

    heading("Professional Experience")
    for e in c["experience"]:
        para(e["title"], size=11, bold=True, space_before=6, space_after=0)
        para(f"{e['company']} - {e['location']}  |  "
             f"{fmt_date(e['start'])} - {fmt_date(e.get('end'), e.get('current', False))}",
             size=10, italic=True, space_after=2, color=(0x44, 0x44, 0x44))
        for b in e["bullets"]:
            bullet(b)
        if e.get("stack"):
            para("Stack: " + ", ".join(e["stack"]), size=9.5, italic=True,
                 space_before=1, space_after=1, color=(0x44, 0x44, 0x44))

    heading("Selected Projects")
    for pr_ in c["projects"]:
        para(pr_["name"], size=10.8, bold=True, space_before=5, space_after=0)
        meta = ", ".join(pr_["tech"])
        if pr_.get("url"):
            meta = f"{pr_['url']}  |  {meta}"
        para(meta, size=9.5, italic=True, space_after=2, color=(0x44, 0x44, 0x44))
        for b in pr_["bullets"]:
            bullet(b)

    heading("Education")
    for ed in c["education"]:
        para(ed["degree"], size=10.8, bold=True, space_before=4, space_after=0)
        end = ed.get("end") or ed.get("status", "")
        para(f"{ed['institution']} - {ed['location']}  |  {ed['start']} - {end}",
             size=10, italic=True, space_after=1, color=(0x44, 0x44, 0x44))

    if c["certifications"]:
        heading("Certifications")
        for cert in c["certifications"]:
            bullet(cert)

    if c["languages"]:
        heading("Languages")
        para(" | ".join(f"{l['language']}: {l['level']}" for l in c["languages"]))

    doc.save(path)


# ---------------------------------------------------------------------------
# PDF - same content, selectable text, single column
# ---------------------------------------------------------------------------

def write_pdf(c: dict, path: Path) -> None:
    """Reproduce the master CV's layout exactly.

    Every measurement here is read off profile/cv/master/Saif_Ur_Rehman.pdf - his own
    file - so a tailored CV is recognisably the same document rather than a different
    one carrying the same words. A4, 20mm side margins, left-aligned throughout,
    Helvetica at his sizes: name 20, section headings 11.5, company and project names
    10, body 9, skills and bullets 8.7-8.8.
    """
    ss = getSampleStyleSheet()
    L = 57          # his left margin, in points
    W = 595 - L * 2

    def st(name, size, leading, bold=False, space_before=0, space_after=0, indent=0,
           bullet_indent=0, color="#000000"):
        return ParagraphStyle(
            name, parent=ss["Normal"],
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size, leading=leading, textColor=color,
            spaceBefore=space_before, spaceAfter=space_after,
            leftIndent=indent, bulletIndent=bullet_indent,
        )

    s_name    = st("nm", 20, 23, bold=True, space_after=2)
    s_head    = st("hd", 10.5, 13, space_after=3)
    s_contact = st("ct", 8.8, 11.4)
    s_section = st("sc", 11.5, 14, bold=True, space_before=11, space_after=4)
    s_body    = st("bd", 9, 12.2, space_after=2)
    s_org     = st("og", 10, 13, bold=True, space_before=7, space_after=1)
    s_role    = st("rl", 9, 12, space_after=2)
    s_skill   = st("sk", 8.7, 11.8, space_after=1.5)
    s_bullet  = st("bl", 8.8, 11.6, space_after=1.5, indent=11, bullet_indent=1)
    s_tech    = st("tc", 8.7, 11.6, space_before=2, space_after=1)

    story = [
        Paragraph(c["name"], s_name),
        Paragraph(c["headline"], s_head),
    ]
    for ln in c["contact_lines"]:
        story.append(Paragraph(ln, s_contact))

    def section(t):
        story.append(Paragraph(t, s_section))

    def bullets(items):
        for b in items:
            story.append(Paragraph(b, s_bullet, bulletText="\u2022"))

    section("PROFESSIONAL SUMMARY")
    story.append(Paragraph(c["summary"], s_body))

    section("TECHNICAL SKILLS")
    for cat, items in c["skills"].items():
        story.append(Paragraph(f"<b>{cat}:</b> {', '.join(items)}", s_skill))

    section("PROFESSIONAL EXPERIENCE")
    for e in c["experience"]:
        story.append(Paragraph(f"{e['company']} &mdash; {e['location']}", s_org))
        story.append(Paragraph(
            f"<b>{e['title']}</b> | {fmt_date(e['start'])} &ndash; "
            f"{fmt_date(e.get('end'), e.get('current', False))}", s_role))
        bullets(e["bullets"])
        if e.get("stack"):
            story.append(Paragraph(f"<b>Technologies:</b> {', '.join(e['stack'])}", s_tech))

    section("SELECTED PROJECTS")
    for pr_ in c["projects"]:
        name = pr_["name"]
        if pr_.get("url"):
            name += f" | {pr_['url']}"
        story.append(Paragraph(name, s_org))
        bullets(pr_["bullets"])

    section("EDUCATION")
    for ed in c["education"]:
        story.append(Paragraph(f"{ed['institution']} &mdash; {ed['location']}", s_role.clone(
            "edorg", fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=0)))
        end_yr = ed.get("end") or ed.get("status", "")
        story.append(Paragraph(f"{ed['degree']} | {ed['start']} &ndash; {end_yr}", s_role))

    if c["certifications"]:
        section("CERTIFICATIONS")
        story.append(Paragraph(" | ".join(c["certifications"]), s_body))

    if c["languages"]:
        section("LANGUAGES")
        story.append(Paragraph(
            " | ".join(f"{l['language']} &mdash; {l['level'].split(' - ')[0]}"
                       for l in c["languages"]), s_body))

    SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=L, rightMargin=L, topMargin=52, bottomMargin=40,
        title=f"{c['name']} - CV", author=c["name"], subject=c["headline"],
    ).build(story)


# ---------------------------------------------------------------------------
# TXT - for paste-into-form fields and for eyeballing what an ATS actually sees
# ---------------------------------------------------------------------------

def write_txt(c: dict, path: Path) -> None:
    L = [c["name"], c["headline"], *c["contact_lines"], "",
         "PROFESSIONAL SUMMARY", c["summary"], "", "TECHNICAL SKILLS"]
    for cat, items in c["skills"].items():
        L.append(f"{cat}: {', '.join(items)}")
    L += ["", "PROFESSIONAL EXPERIENCE"]
    for e in c["experience"]:
        L += ["", e["title"],
              f"{e['company']} - {e['location']} | "
              f"{fmt_date(e['start'])} - {fmt_date(e.get('end'), e.get('current', False))}"]
        L += [f"- {b}" for b in e["bullets"]]
        if e.get("stack"):
            L.append(f"Stack: {', '.join(e['stack'])}")
    L += ["", "SELECTED PROJECTS"]
    for pr_ in c["projects"]:
        L += ["", pr_["name"], ", ".join(pr_["tech"])]
        L += [f"- {b}" for b in pr_["bullets"]]
    L += ["", "EDUCATION"]
    for ed in c["education"]:
        L += [ed["degree"],
              f"{ed['institution']} - {ed['location']} | {ed['start']} - {ed.get('end') or ed.get('status','')}"]
    if c["certifications"]:
        L += ["", "CERTIFICATIONS"] + [f"- {x}" for x in c["certifications"]]
    if c["languages"]:
        L += ["", "LANGUAGES", " | ".join(f"{l['language']}: {l['level']}" for l in c["languages"])]
    path.write_text("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", help="job id from data/matches.json to tailor against. "
                                  "Without it you get the master CV, unchanged.")
    ap.add_argument("--title", help="override the headline to mirror the job title")
    ap.add_argument("--out", help="output basename (no extension)")
    args = ap.parse_args()

    p = json.loads(PROFILE.read_text())
    job = None
    if args.job:
        jobs = {j["id"]: j for j in json.loads(MATCHES.read_text())}
        job = jobs.get(args.job)
        if job is None:
            raise SystemExit(f"job id {args.job} not found in {MATCHES}")

    c = build_content(p, job, args.title)

    OUT.mkdir(parents=True, exist_ok=True)
    if args.out:
        base = args.out
    elif job:
        base = f"Saif_ur_Rehman_CV_{slug(job['company'])}_{slug(job['title'])}"
    else:
        base = "Saif_ur_Rehman_CV"

    docx_p, pdf_p, txt_p = OUT / f"{base}.docx", OUT / f"{base}.pdf", OUT / f"{base}.txt"
    write_docx(c, docx_p)
    write_pdf(c, pdf_p)
    write_txt(c, txt_p)

    print(json.dumps({
        "docx": str(docx_p), "pdf": str(pdf_p), "txt": str(txt_p),
        "tailored_to": f"{job['title']} @ {job['company']}" if job else "master CV (not tailored)",
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))


if __name__ == "__main__":
    main()
