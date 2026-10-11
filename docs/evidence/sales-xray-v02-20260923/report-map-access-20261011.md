# AUT-1677 — Report map control access

Strike A's real shared-dev review found that phone map buttons exposed both
their CSS-generated short label and full text to screen readers. "StagesCall
stages" and "Talk shareTalk share by minute" were the resulting names.

Each existing map control now has one explicit full accessible name: Who talked,
Call stages, or Talk share by minute. The visible phone labels and all three
existing map views remain. Controls meet the owner's 32px desktop/44px phone
height requirement, using existing semantic styles and no new colors. Source
selection, confirmed speaker roles and report content are unchanged.

The bounded browser journey uses the existing populated fictional full-shell
fixture on shared dev, without editing shell files or starting a server/build.
Its exact accessible-name lookup failed on the original phone UI. After the
committed refresh it checks all three buttons, keyboard activation, one pressed
view, desktop/phone heights, source seek callback, theme, overflow, errors and
unexpected API/external requests. Screenshots and exact source receipts are
retained in strike NOTES.md; no authenticated production acceptance is claimed.

All 17 focused existing CallMap cases, incremental typecheck, cached
changed-file ESLint/Prettier, browser Ruff/format and diff check pass. The
post-commit shared-dev result is recorded separately in the strike notes.
This additive Report-component repair changes no shared shell, token, auth,
migration, provider or persistence behavior.
