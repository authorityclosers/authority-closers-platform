# Alpha brand assets — 7 September 2026

## Scope and implementation

This records the bounded shared-brand and public-asset change within the alpha consolidation lane. The user supplied the learning-v3 and Authority Closers Brand & Motion Kit v0.1 archives; the current task authorizes integration of selected artwork. Archive text was treated as reference data, not repository instructions.

- `packages/typescript/ui/src/brand-presentation.ts` exports serializable display-only descriptors: `COMPANY_BRAND` (Authority Closers), `FIRST_ACADEMY_BRAND` (Closers Academy), and `PLATFORM_BRAND` (provisional Cohorva).
- These constants contain names, presentation roles, source release status, artwork colors, and same-origin asset paths. They contain no tenant IDs, membership rules, permission checks, payment state, scoring, or publication decisions. The first-academy constant is not a tenant resolver.
- `BrandMark` preserves its `SVGProps<SVGSVGElement>` API and renders the supplied Open A company geometry. `AcademyMark` and `PlatformMark` render the exact supplied CA and Cohorva symbol polygons. All use the source 512 × 512 viewBox and inherit `currentColor`; no background-colored cutout masks are needed.
- Marks default to decorative, unfocusable SVGs beside text. A supplied `aria-label` or `aria-labelledby` exposes a named image; explicit SVG accessibility and styling props remain supported.
- Brand artwork colors are separate from semantic UI tokens: company ink #152638, academy teal #173F43, provisional platform blue #3155C6. These values do not recolor baked images or define success/error/progress states.
- Selected source logos, marks, icons and portrait derivatives were visually inspected before integration. Runtime SVGs are byte-identical outlined exports. No live-text font dependency, source installer, prototype script, demonstration course video, audio, model, research pack, draft answer key or full archive was copied into public assets.
- This subtask did not change existing root icons, service workers, manifests, tenant selection, routes, or learner/admin TSX. Shell and manifest integration is recorded by the main alpha lane.

Initial checkpoint public/brand inventory: **24 files, 147,798 bytes**. Learner: 14 files / 115,314 bytes. Admin: 10 files / 32,484 bytes. The pass2 addition below supersedes these inventory totals without changing the initial assets. These are total stored assets, not the initial page transfer size.

## Supplied package verification

Source package paths relative to this worktree:

- `.tmp/alpha-consolidation-20260907/brand-v01/Authority_Closers_Brand_Kit_v0_1/`
- `.tmp/alpha-consolidation-20260907/learning-v3/`

Learning package: 1,274 files, 156,859,700 bytes; all 1,272 payload entries match both the package manifest and SHA256SUMS. The two excluded metadata files are the manifest and checksum list themselves. Brand package: 707 files, 63,557,494 bytes; all 706 payload paths, sizes and hashes match the manifest, which excludes itself. Learning installer/staging manifests also match 573/573 and 318/318 entries; they are source inventories, not runtime allowlists.

Static inspection found no script, event handler, foreignObject, DTD/entity or JavaScript-URI markers in 292 learning and 213 brand SVGs. No nonembedded external SVG references were found; one brand-book page embeds a PNG. Current HTML/CSS preview references resolve when honoring the learning entrypoint's base element; unresolved references are limited to retained history and unbuilt templates. No bundled code was executed. This is bounded static evidence, not a claim that every package script or dynamically generated reference is safe.

## Byte-preserving runtime allowlist

The following nine SVGs appear identically under both `apps/learner-web/public/brand/` and `apps/admin-web/public/brand/`. Source paths below are relative to the brand package root.

| Runtime path beneath public/brand     | Supplied source                                             |  Bytes | SHA-256                                                            |
| ------------------------------------- | ----------------------------------------------------------- | -----: | ------------------------------------------------------------------ |
| `ac-v0.1/horizontal.svg`              | `02_LOGOS/AC_horizontal_ink.svg`                            | 10,174 | `ca8e5107c1eeb40887fd4b583e528c3d33cf4311340930255843d9ae8f9cad81` |
| `ac-v0.1/symbol.svg`                  | `02_LOGOS/AC_symbol_ink.svg`                                |    461 | `27ca4a9480a179517095630766ce232f8c6f5033658ba93a1723e7007b13c7fb` |
| `ac-v0.1/icon.svg`                    | `02_LOGOS/AC_app_icon.svg`                                  |    573 | `65fdb71975218df44800e1a4cb4a08dd8940c9af5bd53e11baeeedf06fceb215` |
| `closers-academy-v0.1/horizontal.svg` | `14_CLOSERS_ACADEMY_STARTER/logos/CA_horizontal_colour.svg` | 11,544 | `a9173b6c8586fee76f2420e343edae847ad793f5d7f24f570eda41bad71be5a8` |
| `closers-academy-v0.1/symbol.svg`     | `14_CLOSERS_ACADEMY_STARTER/logos/CA_symbol_colour.svg`     |    565 | `c7cad953f39cfeac6cc8f2ee051e6fad2a2cf0fa3f1275a423db6d804ee4625e` |
| `closers-academy-v0.1/icon.svg`       | `14_CLOSERS_ACADEMY_STARTER/logos/CA_app_icon.svg`          |    689 | `75a931a8a308e8524b7c32d9dff7ce9b8811faf32622576e4464dcfe4ef0d1d9` |
| `cohorva-v0.1/horizontal.svg`         | `15_COHORVA_LMS_STARTER/logos/LMS_horizontal_colour.svg`    |  5,514 | `249b562eebbc3540ac94657c1e472af74111650a96558daeb94edc48e15430f1` |
| `cohorva-v0.1/symbol.svg`             | `15_COHORVA_LMS_STARTER/logos/LMS_symbol_colour.svg`        |    610 | `d5e2b9e1b4b9f980dc70638c6870f9afec767d3f3bcdc76d41507fa8bd41faa2` |
| `cohorva-v0.1/icon.svg`               | `15_COHORVA_LMS_STARTER/logos/LMS_app_icon.svg`             |    738 | `75d1b7beeeb554dfc8ce50bc6acaa6ac5fe620011246930fb637059b40d761f4` |

Additional learner-only assets:

| Runtime path beneath public/brand   | Supplied source                                                         |  Bytes | SHA-256                                                            |
| ----------------------------------- | ----------------------------------------------------------------------- | -----: | ------------------------------------------------------------------ |
| `closers-academy-v0.1/icon-180.png` | Brand: `14_CLOSERS_ACADEMY_STARTER/logos/CA_icon_180.png`               |  4,281 | `fda4867411d5d71c8d6af35384bc9167685c66dd07637a6ae210a400d0cbf0b0` |
| `closers-academy-v0.1/icon-192.png` | Brand: `14_CLOSERS_ACADEMY_STARTER/logos/CA_icon_192.png`               |  4,235 | `fc10e52eed1d810b01eb47f2240ae58cfcc2dd514a10086d32f5cfc72aa4b30f` |
| `closers-academy-v0.1/icon-512.png` | Brand: `14_CLOSERS_ACADEMY_STARTER/logos/CA_icon_512.png`               |  4,098 | `9bd2911772a274c3b5e996da98b45a0bd8515907687e61551e37f144e563f57d` |
| `instructor-v1/editorial.webp`      | Learning: `03_assets/photography/instructor-editorial.webp` (768 × 960) | 59,648 | `44d6ab558a9980db63bf42b8a0142a094ac4aedf123a876881c188b1c1a6effe` |
| `instructor-v1/avatar.webp`         | Learning: `03_assets/photography/instructor-avatar.webp` (256 × 256)    | 12,184 | `feaeb766fa03d771d5d5647553ab83752a7cee34efd0dca35a433f2a8c02607b` |

Additional admin-only asset:

| Runtime path beneath public/brand | Supplied source                                        | Bytes | SHA-256                                                            |
| --------------------------------- | ------------------------------------------------------ | ----: | ------------------------------------------------------------------ |
| `cohorva-v0.1/icon-180.png`       | Brand: `15_COHORVA_LMS_STARTER/logos/LMS_icon_180.png` | 1,616 | `45fae2a38afe571d705739dd6ca6043918192236281dd37820eeb889722b5cbe` |

## Portrait and legacy-logo Drive provenance

The authenticated Google Drive connector verified metadata and traversed [LOGO & Pictures-AC](https://drive.google.com/drive/folders/1PFVnBIwUV5tFNMhPFMQtiV2QFu5MW_oR), then its [Founder Photos](https://drive.google.com/drive/folders/1s62ybsDdB4gikMrzF8FbSR9LamIR4Th3) and [Logo](https://drive.google.com/drive/folders/1XYBTfjlE7ltKpyfo4S0IvVhl_NU35Uls) children. Both original file IDs were fetched through the connector. Since raw fetch returned unmaterializable sediment references, the already-public original bytes were streamed from Google Drive into memory for a SHA-256 comparison, with HTTP 200 and the expected image MIME types. No Drive content or sharing changed.

- Portrait original: [DSC06998.jpeg](https://drive.google.com/file/d/1RI-0VWPdgZteSK65Xh1I-vknXp6RCOkF/view?usp=drivesdk), ID `1RI-0VWPdgZteSK65Xh1I-vknXp6RCOkF`, 2,383,687 bytes, SHA-256 `02b2115463253cd1dc700cc2ad6cbfa1407d20b74b9e3f9109e8a78f9e0fa3ca`. Exact match to learning `03_assets/photography/instructor-original.jpg`.
- Legacy logo: [Authority Closers_PNG (1).png](https://drive.google.com/file/d/1bIjkRq4DAJtk9TIKbTXbcMvF6asAeF9i/view?usp=drivesdk), ID `1bIjkRq4DAJtk9TIKbTXbcMvF6asAeF9i`, 2,041,412 bytes, SHA-256 `ff3bc013746e5129571cbd25a22ba9005a9192222c2754e8847a7e2d9dfc8e33`. Exact match to learning `03_assets/vectors/brand/legacy-ac-logo-original.png`; this legacy raster is not in the runtime allowlist.
- The source portrait derivatives and their crop recipes are retained in the learning package. Instructor attribution follows supplied project context and source-folder provenance; no identity was inferred from facial appearance.
- Both originals have anyone-reader permissions. Sharing and byte equality establish source access and equivalence, not model release, publication rights or trademark registration. No independent rights verification is claimed.
- The brand source calls the company kit a v0.1 proposal, CA a starter concept, and Cohorva a provisional name. Those source-status distinctions remain explicit in the descriptors; package text does not set protected business semantics.

## App-icon safe-zone evidence

The [W3C Web Application Manifest working draft, section 2.3](https://www.w3.org/TR/appmanifest/#icon-masks-and-safe-zone) defines the guaranteed maskable safe area as a centered circle with radius 40% of the smaller icon dimension. On 7 September 2026, each selected PNG was decoded with Windows System.Drawing and every pixel was inspected. Foreground was any pixel differing from the corner background, including antialiased edges. All four images are fully opaque and have zero foreground pixel centers outside the safe circle.

| Icon        |    Pixels | Background | Maximum foreground radius | Safe radius | Outside / nonopaque pixels |
| ----------- | --------: | ---------- | ------------------------: | ----------: | -------------------------- |
| CA 180      | 180 × 180 | #173F43    |                    67.413 |          72 | 0 / 0                      |
| CA 192      | 192 × 192 | #173F43    |                    72.101 |        76.8 | 0 / 0                      |
| CA 512      | 512 × 512 | #173F43    |                   188.580 |       204.8 | 0 / 0                      |
| Cohorva 180 | 180 × 180 | #3155C6    |                    67.235 |          72 | 0 / 0                      |

The smallest measured margin is over four pixels, also covering pixel corners beyond the center-point measurement. These selected PNGs can be designated maskable without cropping the mark. This does not claim device installation or browser-launcher testing. Root icon files were not overwritten.

## Verification

Required runtime: Node 24.19.0, pnpm 11.19.0.

- `pnpm --filter @ac/learner-web exec vitest run app/lib/brand-presentation.test.ts`: 19/19 pass under Node 24.19.0. Covers serializable identity separation, same-origin assets on both apps, exact source geometry, decorative/named accessibility behavior, SVG prop compatibility, the complete public/brand file and hash allowlist, passive self-contained outlined SVGs, and PNG dimensions.
- `pnpm --filter @ac/ui typecheck`: pass under Node 24.19.0.
- Targeted Prettier formatting was applied only to this subtask's shared source, focused test and evidence. `pnpm --filter @ac/learner-web exec eslint app/lib/brand-presentation.test.ts --max-warnings 0`: pass under Node 24.19.0.
- Initial 15-test/typecheck runs under Node 22 also passed but do not replace the required Node 24 verification.
- No staging, commit, deployment, process restart, database change, or external publication was performed by this subtask.

## Presentation pass2 addition

The subsequent user-authorized presentation pass selects only these three byte-identical decorative object WebPs from learning `11_visual_upgrade/assets/webp/`, after inspecting the actual assets and the supplied Today desktop/mobile boards. Each source is 960 × 840. The images contain no baked program title, score, earned badge, state or playback affordance. They are not program metadata or instructor assignment.

| Learner runtime path beneath public/brand | Source file       |  Bytes | SHA-256                                                            |
| ----------------------------------------- | ----------------- | -----: | ------------------------------------------------------------------ |
| `learning-art-v1/discovery.webp`          | `discovery.webp`  | 41,940 | `7672d4cba35748fe60aa0c6777fdf010a57d2f6548444bbb52abdc2c74f21882` |
| `learning-art-v1/reflection.webp`         | `reflection.webp` | 32,748 | `9b640d53ad2c951d0884d037b26983a03a845e34374e9655a3f97cc29c644a90` |
| `learning-art-v1/next-move.webp`          | `next-move.webp`  | 30,966 | `df451fd23e75c27c7932bc71c8cb95c6543c3414ca3a44f6bf973185496e84e7` |

The added inventory is **3 files / 105,654 bytes**. Current total: **27 files / 253,452 bytes**; learner **17 / 220,968**, admin unchanged **10 / 32,484**. No masters, prototype JS, videos, audio, models or baked `shift-*` course covers entered runtime. The existing verified portrait derivative is reused, not duplicated.

`ACADEMY_ARTWORK` and `INSTRUCTOR_PORTRAIT` provide serializable, trusted presentation descriptors. `CourseArtwork` accepts only an allowlisted decorative kind and compact mode; it accepts no arbitrary source URL, server title, access state or playback data. `InstructorPortrait` preserves intrinsic dimensions and supports a meaningful editorial alt or decorative use beside the visible academy attribution. The complete runtime file/hash allowlist test now includes all three WebPs.

Pass2 implementation, fixture QA and remaining route gaps are recorded in [20260907_ALPHA_PRESENTATION_PASS2.md](20260907_ALPHA_PRESENTATION_PASS2.md). No new Drive rights or trademark assertion is made.

## Front-facing founder photograph — subsequent user feedback

The user requested a welcoming front-facing portrait in the learner Home card.
Three originals were collected from the exact verified Founder Photos folder
`1s62ybsDdB4gikMrzF8FbSR9LamIR4Th3`, not identified by facial recognition.
Root inspected the seated front-facing alternative and selected the smiling
standing photograph, **DSC06816.jpeg**, Drive ID
`1eZtjAMRJE30jdigN33zTkbnbCvW5FzHY`. Metadata confirmed its parent, JPEG MIME,
2,011,586-byte size and pre-existing anyone-reader permission. Permissions were
not changed. SHA-256:
`659f4ae78271e97962d2e4c2b0120a3d191facd0bf9eca3f140bb3ef126d6c68`.

The byte-identical 3074×3864 source is now
`apps/learner-web/public/brand/instructor-v2/front-facing.jpeg`. No generative
face modification or retouching was performed. The versioned original remains
available to the existing Next Image server optimizer; the browser uses its
responsive optimized URL and srcset. This deliberately adds a 2 MB server-side
source, not a 2 MB initial portrait request. The older derivatives are retained
for historical/other uses and are not silently overwritten.

Verification: 37 focused UI tests passed. Eight mounted Home/public-page
390/1440 light/dark fixture cases passed with no recorded failures in
`screenshots/alpha-front-facing-2026-09-07/run-20260907T134607Z`. An actual
same-origin Next Image request at width 640/quality 75 with WebP acceptance
returned **HTTP 200 / image/webp / 31,438 bytes**. This is a measured derivative
response, not a cold-load/Core Web Vitals or production acceptance claim.
The full updated allowlist is 28 files / 2,265,038 bytes; learner 18 files /
2,232,554 bytes; admin unchanged. This follow-up is not in release `851ebc8`.

Mobile focal follow-up: the Home portrait uses `object-position: 50% 42%` so the
selected face remains comfortably inside the narrow card. Four additional Home
320/390 light/dark cases passed in
`screenshots/alpha-front-facing-2026-09-07/after-focal/run-20260907T135111Z`.
Independent review reran all 37 focused tests and inspected six screenshots
including the corrected mobile crop: no Critical/Important findings. No GPS
latitude/longitude metadata was found in the selected original. These are local
fixture checks, not real-user performance or live deployment evidence.
