# Sales Xray v0.2 — "Lightbox" design package (24 Sep 2026)

A calm light table for sales calls: the call is the film, the moments light up, the coaching sits in the margin.

| File | For | What it is |
|---|---|---|
| `CODEX_UI_HANDOFF.md` | Codex | How to run Claude, divide the work, integrate and release. Includes the urgent backup findings. |
| `CLAUDE_UI_BRIEF.md` | Claude Code (Opus 5.5, xhigh) | What Claude reads on every run: phases P0–P6, rules, gates, report format. |
| `run-claude-ui.ps1` | Codex | Runner with verified CLI flags and locked-down permissions. Usage is in its header. |
| `DESIGN_SPEC.md` | Everyone | IA, screens, data mapping, motion catalogue, copy, accessibility, performance, acceptance. **Authoritative for behaviour.** |
| `tokens.css` | Implementation | Colour, type, space, radius, elevation and motion tokens (light plus dark), and the Devanagari rules. |
| `assets/lens/*.svg` | Implementation | The Lens character: ready (idle), listening, understanding, writing, done, paused. Inline these in React so the animations run. |
| `assets/glyphs/lightbox-glyphs.svg` | Implementation | Semantic glyph sprite: moment kinds, skill evidence states, chapters, journey. |
| `assets/illustrations/*.svg` | Implementation | Empty calls, offline. |
| `prototype/canvas/project/*.dc.html` | Visual reference | 10 boards: foundations, the desktop journey, report, states, mobile. |
| `prototype/_asset-sheet.html` | Visual check | Contact sheet of the SVG assets. Serve this folder over HTTP to view it. |

**Canvas:** https://claude.ai/artifact/5TYWjU7XhUd3gVGV2HzLKS (private to Suyash until shared from its Share menu).

**About the prototype boards:**
- They are design-canvas components. `./support.js` and the `{{holes}}` only render inside the canvas.
- Opened as plain HTML, the layout, type and copy render, but the illustrative waveforms don't.
- Production waveforms must always come from measured data.
