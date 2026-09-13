"""Check a generated CV against what applicant tracking systems actually parse.

This reports facts, not a score. No public ATS publishes a scoring formula, and any
tool claiming "94% ATS compatible" invented that number. What can be checked is whether
the machine reading the file recovers the same document a person sees:

  * does the text extract at all, in reading order
  * are the section headings ones a parser recognises
  * are contact details, dates and job titles in the extracted text
  * is the file free of the structures that break parsers - tables, multiple columns,
    text boxes, images, headers and footers
  * are keywords present as words, not only inside graphics

Usage:  python profile/cv/ats_check.py [path/to/cv.pdf]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

STANDARD_HEADINGS = [
    "PROFESSIONAL SUMMARY", "SUMMARY", "TECHNICAL SKILLS", "SKILLS",
    "PROFESSIONAL EXPERIENCE", "EXPERIENCE", "WORK EXPERIENCE",
    "EDUCATION", "CERTIFICATIONS", "LANGUAGES", "SELECTED PROJECTS", "PROJECTS",
]
# Accept full month names too. The abbreviation-only pattern reported "0 dates" on a
# CV using "March 2025", which was the checker being wrong, not the CV.
DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\+\d[\d\s]{7,}")


def check(path: Path) -> int:
    import pymupdf

    doc = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in doc)
    ok, warn, fail = [], [], []

    def line(bucket, msg):
        bucket.append(msg)

    # --- extraction ---
    if len(text.strip()) < 800:
        line(fail, f"only {len(text.strip())} characters extract - the text may be an image")
    else:
        line(ok, f"{len(text.split())} words extract cleanly as selectable text")

    # --- structures that break parsers ---
    images = sum(len(p.get_images(full=True)) for p in doc)
    line(ok if images == 0 else fail,
         "no images" if images == 0 else f"{images} image(s) - parsers drop text inside them")

    tables = sum(len(p.find_tables().tables) for p in doc)
    line(ok if tables == 0 else fail,
         "no tables" if tables == 0 else f"{tables} table(s) - a common cause of scrambled parsing")

    # column detection: are there two distinct text blocks side by side on a line?
    multicol = 0
    for page in doc:
        blocks = [b for b in page.get_text("blocks") if b[4].strip()]
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                if abs(a[1] - b[1]) < 6 and abs(a[0] - b[0]) > 180:
                    multicol += 1
    line(ok if multicol == 0 else warn,
         "single column" if multicol == 0 else f"{multicol} side-by-side block pair(s) - check column layout")

    # --- headings ---
    found = [h for h in STANDARD_HEADINGS if h in text.upper()]
    line(ok if len(found) >= 5 else warn,
         f"{len(found)} standard section headings recognised: {', '.join(found[:7])}")

    # --- contact block ---
    for label, rx in (("email", EMAIL_RE), ("phone", PHONE_RE)):
        line(ok if rx.search(text) else fail, f"{label} {'found' if rx.search(text) else 'MISSING'} in the text")
    line(ok if "linkedin.com/in/" in text.lower() else warn, "LinkedIn URL present")

    # --- dates ---
    dates = DATE_RE.findall(text)
    # Two roles produce three month-dates once the current one ends in "Present"; degree
    # rows carry years only, which is normal. The old threshold of four was arbitrary and
    # warned on a perfectly parseable CV.
    line(ok if len(dates) >= 3 else warn,
         f"{len(dates)} month-and-year dates - the format parsers handle most reliably")

    # --- fonts ---
    fonts = {s.split("+")[-1] for p in doc for f in p.get_fonts(full=True) for s in [f[3]]}
    exotic = [f for f in fonts if not any(k in f for k in ("Helvetica", "Arial", "Times", "Calibri", "Courier"))]
    line(ok if not exotic else warn,
         f"fonts: {', '.join(sorted(fonts))}" + (" - non-standard face" if exotic else ""))

    # --- length ---
    line(ok if doc.page_count <= 2 else warn,
         f"{doc.page_count} page(s)" + (" - two is the ceiling for this level" if doc.page_count > 2 else ""))

    print(f"\n  {path.name}\n")
    for m in ok:
        print(f"   PASS  {m}")
    for m in warn:
        print(f"   WARN  {m}")
    for m in fail:
        print(f"   FAIL  {m}")
    print(f"\n   {len(ok)} pass, {len(warn)} warn, {len(fail)} fail\n")
    return 1 if fail else 0


def compare_to_master() -> int:
    """Assert the untailored build still says exactly what his master CV says.

    The generator exists only so a tailored CV looks like his document. If the two
    drift apart, a tailored application stops being recognisably the same CV - and
    that drift would otherwise go unnoticed until an employer saw both.
    """
    import difflib
    import re

    import pymupdf

    def words(path):
        t = "\n".join(pg.get_text() for pg in pymupdf.open(path))
        t = t.replace("\u2014", "-").replace("\u2013", "-").replace("\u2022", "-")
        return re.sub(r"[ \t]+", " ", t).split()

    master = ROOT / "profile/cv/master/Saif_Ur_Rehman.pdf"
    built = ROOT / "profile/cv/generated/Saif_ur_Rehman_CV.pdf"
    if not built.exists():
        print("   FAIL  no untailored build to compare - run build_cv.py first")
        return 1
    a, b = words(master), words(built)
    sm = difflib.SequenceMatcher(None, a, b)
    diffs = [op for op in sm.get_opcodes() if op[0] != "equal"]
    print(f"\n  generator vs your master CV: {sm.ratio() * 100:.1f}% word match")
    if not diffs:
        print("   PASS  identical wording\n")
        return 0
    for tag, i1, i2, j1, j2 in diffs[:10]:
        print(f"   FAIL  {tag}: yours={' '.join(a[i1:i2])[:70] or '-'} "
              f"| built={' '.join(b[j1:j2])[:70] or '-'}")
    print()
    return 1


if __name__ == "__main__":
    if "--compare" in sys.argv:
        raise SystemExit(compare_to_master())
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = Path(paths[0]) if paths else ROOT / "profile/cv/master/Saif_Ur_Rehman.pdf"
    raise SystemExit(check(target))
