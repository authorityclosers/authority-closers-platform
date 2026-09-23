# Sales skills typography QA — 2026-09-24

The production `SalesSkills` card style used a 12 px heading at desktop heights of 740 px or less. At 1280 × 720, each of four cards measured 276 px wide, leaving room for a readable heading. The card now uses a 13–14 px responsive heading in that compact state. At mobile widths, headings are 13 px, status labels 11 px, and **Open notes** buttons 12 px. The report text, evidence, behavior, and card layout are unchanged.

Browser checks on the synthetic report route (which mounts the production component):

| Viewport | Heading after | Horizontal document width | Result |
| --- | --- | --- | --- |
| 1024 × 720 | 13 px | 1009 px | Four 219 px cards; no horizontal overflow |
| 1280 × 720 | 14 px | 1265 px | Four 276 px cards; no horizontal overflow |
| 390 × 844 | 13 px | 375 px | Mobile card labels and actions remain inside the viewport |

The Sales skills and Report Explorer tests passed (10/10). Web typecheck, CSS Prettier check, and `git diff --check` passed. This verifies presentation with invented dialogue; it does not validate generated report content or coaching quality.
