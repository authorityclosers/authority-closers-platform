# Authority LMS admin/studio visual QA

Date: 2026-08-31
Scope: admin/studio foundation only
Visual direction: Clarity Grid / Direction A

## Source visual truth

- Organization: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references\ORG-01-desktop-overview.png` — 1568 × 1003 px.
- People: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references\PEOPLE-01-desktop-assignment.png` — 1570 × 1001 px.
- Studio: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references\STUDIO-01-desktop-course-outline.png` — 1536 × 1024 px.

The references are design direction and sample-data compositions. Controlled route contracts and admin boundary rules take precedence over sample metrics, people, assignments, publishing, or studio mutations.

## Rendered implementation evidence

- Organization desktop: `docs/evidence/screenshots/v0.1-drive-aligned/07-admin-overview-desktop.png` — 1440 × 900 px viewport capture.
- People desktop: `docs/evidence/screenshots/v0.1-drive-aligned/08-admin-people-desktop.png` — 1440 × 900 px viewport capture.
- Studio desktop: `docs/evidence/screenshots/v0.1-drive-aligned/09-admin-studio-desktop.png` — 1440 × 900 px viewport capture.
- Organization, People, Studio mobile captures: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-admin-qa\org-mobile-viewport.png`, `people-mobile-viewport.png`, `catalog-mobile-viewport.png` — 375 × 811 px visible content from a 390 × 844 px browser viewport. No density scaling was applied; browser scrollbar accounts for the content-width difference.

Final source-sized combined comparison inputs are saved at `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-final-qa\admin-org-comparison-final.png`, `admin-people-comparison-final.png`, and `admin-studio-comparison-final.png`. Each places the approved Drive source and the current rendered route in one review image.

## State and interactions tested

- Local development preview with `AC_ADMIN_LOCAL_PREVIEW=1`; this bypasses only the local route gate. The admin session provider and real same-origin API boundary were not altered. Tenant copy remains pending until the session is verified and never displays an unverified tenant name.
- Organization route: `/`.
- People route: `/people`, empty directory state, disabled invite/assignment/filter controls.
- Studio route: `/catalog`, contract outline, pending-media state, disabled resolve/delete/publish controls.
- People → Catalog navigation completed through the rendered navigation.
- Desktop and 390 px responsive layouts checked for all three routes.
- Final mobile document overflow: 0 px on all three routes.
- Final mobile action state: 0 enabled buttons and 6 disabled buttons on the studio route.
- Browser console errors: none observed.
- Mobile interactive and disabled-control targets are at least 44 × 44 CSS pixels; the 390 px document remains overflow-free.

## Findings

- `[expected / controlled]` The references show sample metrics, named learners, assignments, and editable course content. The implementation shows `Not connected`, an empty directory, and a locked studio because those data and mutation APIs are not part of the current admin foundation. This is an intentional truthfulness difference, not a visual defect.
- `[fixed P2]` Initial mobile render let the legacy table intrinsic width expand the admin frame. The shell now constrains the sidebar and grid-item min widths while preserving internal table scrolling. Final render is 0 px document overflow at 390 px.
- `[accepted P3]` The existing reference uses denser sample-data rows and more secondary admin nav items. The implementation keeps the same hierarchy and labels unavailable future surfaces instead of implying routes or capabilities that do not exist.

## Fidelity review

- Fonts and typography: Inter/IBM Plex Mono are used to match the reference’s compact enterprise hierarchy; the large display title was reduced to the reference scale.
- Spacing and layout rhythm: 8px-oriented spacing, 252px desktop rail, bordered cards, compact header, three-pane studio grid, and responsive single-column collapse are implemented.
- Colors and visual tokens: Clarity Grid light surfaces, navy ink, indigo-blue action color, pale blue selected states, amber preview warnings, and restrained borders/shadows are tokenized in the scoped shell layer.
- Image quality and asset fidelity: the existing Authority brand mark is retained; all visible functional icons use the existing icon library. No sample data image or fabricated artwork is introduced.
- Copy and content: unavailable data and mutations are named explicitly; no sample people, metric values, publish state, or media readiness is asserted.

## Comparison history

1. Initial desktop comparison identified broad drift from the dark editorial shell. Fixed by adding the scoped Clarity Grid admin/studio layer and the three target compositions.
2. Initial mobile comparison identified horizontal overflow from the legacy table intrinsic width. Fixed with `width: 100%`/`min-width: 0` constraints on the shell and sidebar; internal tables remain scrollable.
3. Post-fix desktop and mobile captures were re-rendered and reviewed against the combined comparison inputs. No actionable P0/P1/P2 visual findings remain.

## Final result

passed
