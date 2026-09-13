# The master CV

`Saif_Ur_Rehman.pdf` is Saif's own file, byte for byte as he wrote it. It is **not
generated** and must never be overwritten by a build.

This is what gets attached to an application unless that role's *Tailor the CV to this
posting* switch is on in the portal. Untouched by default: no re-rendering, no rewording,
no reordering.

`profile/cv/build_cv.py` exists only for the tailored case, and reproduces this file's
layout exactly - same fonts, sizes, margins, section order and wording - so a tailored CV
is recognisably the same document with its skills and projects reordered around one
posting. `ats_check.py --compare` asserts the generator's untailored output still matches
this file's text, so the two cannot drift apart silently.

To replace the master: drop the new PDF in here under the same name, run
`python profile/cv/build_cv.py --sync-profile` to pull its text into
`profile/master-profile.json`, and check `ats_check.py --compare` still passes.
