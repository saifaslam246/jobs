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
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE = ROOT / "profile" / "master-profile.json"
MATCHES = ROOT / "data" / "matches.json"
OUT = ROOT / "profile" / "cv" / "generated"

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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

def build_content(p: dict, variant: str, job: dict | None, title_override: str | None) -> dict:
    ident = p["identity"]
    headline = title_override or ident["headline"]

    contact = [ident["location"], ident["phone"], ident["email"]]
    links = [ident["github"], ident["linkedin"]]
    if ident.get("portfolio_public") and ident.get("portfolio"):
        links.append(ident["portfolio"])

    summary = p["summary_variants"].get(variant, p["summary_variants"]["fullstack"])

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
            d = sum(3 for x in pr["domain"] if mentions(x))
            # Weight counts double: when a posting is generic prose - as agency and
            # consultancy ads usually are - the strongest work should lead, not whichever
            # project happens to share two framework names.
            return -(t + d + pr.get("weight", 0) * 2)

        projects.sort(key=relevance)
    projects = projects[:4]
    # two bullets per project keeps the CV to two pages; the third is detail the
    # interview is for, not the screen.
    projects = [{**pr, "bullets": pr["bullets"][:2]} for pr in projects]

    return {
        "name": ident["full_name"].upper(),
        "headline": headline,
        "contact_line": "  |  ".join(contact),
        "links_line": "  |  ".join(links),
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
             align=None, color=None, caps=False):
        pr = doc.add_paragraph()
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
        pr.paragraph_format.left_indent = Inches(0.22)
        pr.paragraph_format.first_line_indent = Inches(-0.14)
        pr.paragraph_format.space_after = Pt(1.5)
        run = pr.add_run("•  " + text)
        run.font.size = Pt(10.5)

    # --- header (in the body, not a Word header) ---
    para(c["name"], size=19, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=1)
    para(c["headline"], size=11.5, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2,
         color=(0x33, 0x33, 0x33))
    para(c["contact_line"], size=9.5, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    para(c["links_line"], size=9.5, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)

    heading("Professional Summary")
    para(c["summary"], space_after=2)

    heading("Technical Skills")
    for cat, items in c["skills"].items():
        pr = doc.add_paragraph()
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
    ss = getSampleStyleSheet()
    name = ParagraphStyle("nm", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=19, leading=22, alignment=TA_CENTER, spaceAfter=1)
    head = ParagraphStyle("hd", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=11.5, leading=14, alignment=TA_CENTER, spaceAfter=2,
                          textColor="#333333")
    meta = ParagraphStyle("mt", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=9.2, leading=12, alignment=TA_CENTER, textColor="#222222")
    sec = ParagraphStyle("sc", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=11, leading=13, spaceBefore=10, spaceAfter=4,
                         borderWidth=0, textColor="#000000")
    body = ParagraphStyle("bd", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=10, leading=13.2, spaceAfter=2)
    role = ParagraphStyle("rl", parent=body, fontName="Helvetica-Bold", fontSize=10.8,
                          spaceBefore=6, spaceAfter=0)
    sub = ParagraphStyle("sb", parent=body, fontName="Helvetica-Oblique", fontSize=9.5,
                         textColor="#444444", spaceAfter=2)
    bul = ParagraphStyle("bl", parent=body, fontSize=10, leading=13, spaceAfter=1.5)

    def rule():
        return Paragraph('<para spaceb="0"><font size="1" color="#888888">'
                         + "_" * 200 + "</font></para>", body)

    story = [
        Paragraph(c["name"], name),
        Paragraph(c["headline"], head),
        Paragraph(c["contact_line"].replace("|", "&nbsp;|&nbsp;"), meta),
        Paragraph(c["links_line"].replace("|", "&nbsp;|&nbsp;"), meta),
    ]

    def section(t):
        story.append(Paragraph(t.upper(), sec))

    def bullets(items):
        story.append(ListFlowable(
            [ListItem(Paragraph(i, bul), leftIndent=12) for i in items],
            bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8,
            spaceBefore=0, spaceAfter=2,
        ))

    section("Professional Summary")
    story.append(Paragraph(c["summary"], body))

    section("Technical Skills")
    for cat, items in c["skills"].items():
        story.append(Paragraph(f"<b>{cat}:</b> {', '.join(items)}", body))

    section("Professional Experience")
    for e in c["experience"]:
        story.append(Paragraph(e["title"], role))
        story.append(Paragraph(
            f"{e['company']} - {e['location']} &nbsp;|&nbsp; "
            f"{fmt_date(e['start'])} - {fmt_date(e.get('end'), e.get('current', False))}", sub))
        bullets(e["bullets"])
        if e.get("stack"):
            story.append(Paragraph(f"<i>Stack: {', '.join(e['stack'])}</i>", sub))

    section("Selected Projects")
    for pr_ in c["projects"]:
        story.append(Paragraph(pr_["name"], role))
        m = ", ".join(pr_["tech"])
        if pr_.get("url"):
            m = f"{pr_['url']} &nbsp;|&nbsp; {m}"
        story.append(Paragraph(m, sub))
        bullets(pr_["bullets"])

    section("Education")
    for ed in c["education"]:
        story.append(Paragraph(ed["degree"], role))
        end = ed.get("end") or ed.get("status", "")
        story.append(Paragraph(f"{ed['institution']} - {ed['location']} &nbsp;|&nbsp; "
                               f"{ed['start']} - {end}", sub))

    if c["certifications"]:
        section("Certifications")
        bullets(c["certifications"])

    if c["languages"]:
        section("Languages")
        story.append(Paragraph(
            " &nbsp;|&nbsp; ".join(f"{l['language']}: {l['level']}" for l in c["languages"]), body))

    SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"{c['name'].title()} - CV", author=c["name"].title(),
        subject=c["headline"],
    ).build(story)


# ---------------------------------------------------------------------------
# TXT - for paste-into-form fields and for eyeballing what an ATS actually sees
# ---------------------------------------------------------------------------

def write_txt(c: dict, path: Path) -> None:
    L = [c["name"], c["headline"], c["contact_line"], c["links_line"], "",
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
    ap.add_argument("--variant", default="fullstack",
                    choices=["fullstack", "frontend", "mobile", "backend", "data_scraping"])
    ap.add_argument("--job", help="job id from data/matches.json to tailor against")
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

    c = build_content(p, args.variant, job, args.title)

    OUT.mkdir(parents=True, exist_ok=True)
    if args.out:
        base = args.out
    elif job:
        base = f"Saif_ur_Rehman_CV_{slug(job['company'])}_{slug(job['title'])}"
    else:
        base = f"Saif_ur_Rehman_CV_{args.variant}"

    docx_p, pdf_p, txt_p = OUT / f"{base}.docx", OUT / f"{base}.pdf", OUT / f"{base}.txt"
    write_docx(c, docx_p)
    write_pdf(c, pdf_p)
    write_txt(c, txt_p)

    print(json.dumps({
        "docx": str(docx_p), "pdf": str(pdf_p), "txt": str(txt_p),
        "variant": args.variant,
        "tailored_to": f"{job['title']} @ {job['company']}" if job else None,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))


if __name__ == "__main__":
    main()
