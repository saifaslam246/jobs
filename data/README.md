
## tailor.json

Which postings have the "Tailor the CV to this posting" switch on in the portal.

    {"<job id>": true}

A job listed `true` gets its own CV under `profile/cv/tailored/`, built by
`profile/cv/tailor_switches.py` and attached by `outreach/send.py` in place of the
master. Every other job gets `profile/cv/master/Saif_Ur_Rehman.pdf` unchanged. The
switch itself lives in the portal's database; this file is the copy the repo and the
mailer can read.
