# Validation report

Run date: 2026-09-03  
Package: `AC-WF-LEARNER-SF-V0.1A`  
Validation status: **structural checks passed; runtime/visual gates remain open**

The deterministic validator at `scripts/validate-package.ps1` checks JSON and
CSV parsing, required columns/row width, exact source fetch order, stable ID
uniqueness, cross-artifact flow/screen references, diagram markers, local
artifact paths, and explicit visual-pending/zero-asset consistency. The final
run passed with `187` matrix rows, `11` flows, `38` screens, and `0` visual
assets. No runtime or visual approval is implied by a passing structural check.

## Planned evidence

| Check | Command / artifact | Expected result | Status |
| --- | --- | --- | --- |
| JSON syntax | validator → `ai-design-context.json`, `asset-manifest.json` | strict parse | passed |
| CSV schema | validator → `state-transition-matrix.csv` and `source-manifest.csv` | 17 matrix columns; 23 source rows; all rows parse | passed |
| Stable IDs | validator → flow catalog, inventory, matrix, AI context | no duplicates or unknown references | passed |
| Route/state coherence | validator + manual review | screen IDs and routes agree | passed |
| Visual gate | `03-visual-exploration/README.md` and manifest | pending; 0 assets; no selected direction | intentionally pending |
| Diagram source | `04-ai-context/learner-screen-family.puml` | source present; no renderer claim | present |
| Accessibility | QA checklist; WCAG/MDN links | exact runtime/device evidence required | open |
| Runtime/release | QA checklist | exact SHA/staging/browser proof required | open |

## Known limitations

- No app code was changed by this package.
- No generated raster, editable design file, Drive upload, or Notion task is
  claimed.
- Media/caption/transcript, avatar upload, certificate issuance, plan
  projection, notification delivery, and exact browser/device behavior remain
  capability-specific gates.
