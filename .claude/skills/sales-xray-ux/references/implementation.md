# Implementation notes for the rules

Short recipes for the rules in `SKILL.md` that builders most often get wrong. Paths are relative
to `apps/sales-xray-web/app/` on the dev workbench. Check that a file still exists before you
rely on it; the kit moves fast.

## Use the kit, not one-off markup

| Need | Use |
|---|---|
| Bottom sheet on phones, right panel or centred card on computers | `ui/sheet.tsx` `<Sheet>` (swipe and flick to close; `data-sheet-no-drag` on areas that must not start a drag) |
| Buttons, icon buttons, cards, sections, tabs (at most 5, with icons), stats, tags, list rows, empty states | `ds/` (wrap the page in `<DsScope>` from `ds/scope.tsx`) |
| Colours, glass, motion, radii, type steps | `ui/sx-tokens.css` (`--sx-*`) and `ui/pulse-tokens.css`. No raw hex: the raw-colour ratchet test fails it |
| App-level errors | `notice-center.tsx` `notify()`: a corner card that retries by itself |
| Links between screens | `shell/screen-link.tsx` `<ScreenLink>`: the destination outline appears at once |
| A confirming tap | `ui/haptics.ts` `tick()` |

## Back closes every overlay

The browser back button, the Android back gesture and the hardware back key must close the top
overlay first: sheet, dialog, picker, full-screen search, image viewer, hold menu. Only when no
overlay is open may back leave the screen.

Pattern: each overlay that opens adds one history entry, and a `popstate` closes it.
`settings-open.ts` already does this with a `#settings/<section>` hash; reuse that idea for every
sheet instead of inventing a new one.

```ts
// useBackToClose(open, close): one history entry per open overlay.
// A module counter, not crypto.randomUUID: that is missing on the plain-http dev edge.
let overlaySeq = 0;
useEffect(() => {
  if (!open) return;
  const mark = `sx-overlay-${++overlaySeq}`;
  // Keep the router's own state, or Next treats the pop as a full navigation.
  window.history.pushState({ ...window.history.state, sxOverlay: mark }, "");
  const onPop = () => close();
  window.addEventListener("popstate", onPop);
  return () => {
    window.removeEventListener("popstate", onPop);
    // Closed by a tap, swipe or Escape: remove the entry we added.
    if (window.history.state?.sxOverlay === mark) window.history.back();
  };
}, [open, close]);
```

Checks:
- Never stack sheets. A picker inside a sheet opens as a step inside that sheet (its own history
  entry, a back arrow in the sheet header); one back press undoes one step.
- The X, a scrim tap, a swipe down, Escape and Back all close the same way, through the same
  `close()`; a close that would throw away typed input asks first.
- Tabs, segmented controls and filters change the address with `replaceState`, not
  `pushState`, so Back never steps through toggles.
- On a fresh page load, clear a leftover overlay mark with `replaceState`.
- Navigating from inside a sheet (for example "Open full report") replaces the overlay entry
  instead of leaving a dead entry behind it.
- Android app (Capacitor): a `backButton` listener turns off the default handling, so it must do
  `canGoBack ? history.back() : App.minimizeApp()`. On a top tab other than Home, back goes to
  Home first. Back never shows a blank page or a sign-in screen. Do not rely on `CloseWatcher` or
  `<dialog>` closing on back inside the WebView.
- Escape closes the top overlay on computers. Focus returns to the control that opened it.

## No horizontal overflow

The page must never scroll sideways at 360, 390 or 412 px. Fix the cause; never hide it with
`overflow-x: hidden` on `body` (that also breaks sticky headers).

- Flex and grid children that hold text get `min-width: 0`.
- Long names, emails, numbers and links get `overflow-wrap: anywhere`, or one line with an
  ellipsis plus the full value on the next screen.
- Media and charts get `max-width: 100%`. Never size with `100vw`: it includes the scroll bar.
- A row of chips either wraps, or is a deliberate scroll strip: `overflow-x: auto`,
  `scroll-snap-type: x mandatory`, `overscroll-behavior-x: contain`, a fade on the cut edge, and
  the chosen chip scrolled into view.
- Tables on phones become rows (name line plus one context line); never a sideways table.

Probe in the browser console or a Playwright step:

```js
const w = document.documentElement.clientWidth;
const wide = [...document.querySelectorAll("body *")]
  .filter((el) => el.getBoundingClientRect().right > w + 1)
  .slice(0, 10)
  .map((el) => `${el.tagName}.${el.className}`.slice(0, 80));
({ pageScrolls: document.documentElement.scrollWidth > w, wide });
```

The older sweep harness on ac (`~acdev/scratch/mobile-sweep/sweep2.mjs`) reports overflow,
taps under 44 px, layout shift, contrast and tiny text in `audit.jsonl`, but it is a Playwright
run: since the 20 Oct owner order, run it only for a single page under `nice -n 19 ionice -c3`,
or move the same probes into a `wb-ci --visual` fixture.

## Viewport, safe areas and the keyboard

- `layout.tsx` sets `viewportFit: "cover"` and `interactiveWidget: "resizes-content"`. Keep both.
- The app frame uses `100dvh`; never `100vh` (it hides content behind browser bars). A single
  block that must fit with the bars showing can use `100svh`.
- Never disable zoom (`user-scalable=no`, `maximum-scale=1`). Fields use 16 px text or larger,
  or iOS zooms in on focus.
- Hover-only styles go under `@media (hover: hover) and (pointer: fine)`. Nothing works only on
  hover. Animate only `transform` and `opacity`, under 300 ms, exits faster than entrances; no
  `transition: all`.
- Field validation stays as short text under the field. Everything else that fails (network,
  server, permissions) is a corner card through `notify()` that retries by itself. One failing
  block never blanks the screen: the rest stays usable and the block keeps its last data or a
  quiet placeholder of the same size.
- A submit button sends one request however fast it is tapped; it keeps its label and shows a
  small spinner while the request runs. Search waits about 300 ms after typing stops.
- Bottom bars, sheet footers and the primary action bar pad with `env(safe-area-inset-bottom)`,
  with a fallback value: older Android WebViews report it wrongly. Nothing tappable sits in the
  system gesture area at the screen edges.
- Test with the keyboard open: no fixed bar may cover the focused field.
- Inner scrollers and sheets get `overscroll-behavior: contain`, so a scroll inside a sheet does
  not pull the page or trigger pull-to-refresh.
- A sheet with a text field keeps the field and its Save button above the keyboard.

## Touch

- Targets at least 44 x 44 px (48 px is better on Android), with 8 px between neighbours. Grow a
  small icon's hit area with padding or a pseudo-element, not by making the icon bigger.
- `touch-action: manipulation` on controls removes the double-tap zoom delay.
- Replace the grey tap flash with the kit's pressed state (`--sx-press-scale`), not with nothing.
- Use `onPointerLeave` with a `pointerType === "mouse"` check for hover-only effects; touch taps
  fire leave events after the tap.

## Names with capitals

Display names in Title Case even when they were saved in lower or upper case. Do it at display
time; do not rewrite stored data without an owner-approved data change.

```ts
// "priya shah" -> "Priya Shah"; "RAHUL VERMA" -> "Rahul Verma";
// "d'souza" -> "D'Souza"; "anne-marie" -> "Anne-Marie"; "McDonald" stays as typed.
export function displayName(raw: string): string {
  const name = raw.trim().replace(/\s+/g, " ");
  if (!name) return name;
  const oneCase = name === name.toLowerCase() || name === name.toUpperCase();
  if (!oneCase) return name; // mixed case: the person typed it on purpose
  return name
    .toLowerCase()
    .replace(/(^|[\s\-'’])(\p{L})/gu, (_, sep: string, ch: string) => sep + ch.toUpperCase());
}
```

Inputs that take names use `autocapitalize="words"` and `autocomplete="name"`. Phone fields use
`type="tel"`, `inputmode="tel"` and `autocomplete="tel"`. Set `enterkeyhint` ("next", "done").

## Swipe rows

- Reveal starts after about 10 px of horizontal movement and only when the gesture is more
  sideways than up or down, so vertical scrolling never triggers it.
- Commit at about 35 to 40 percent of the row width or on a quick flick; give a `tick()` at the
  commit point; spring back if released early.
- The revealed area shows an icon and a one-word label on the action's tone colour.
- Every swipe action is also reachable without swiping: the row's hold menu or the lead page.
- Anything that cannot be undone asks first or offers Undo in a corner card for a few seconds.
- With `prefers-reduced-motion`, the row snaps instead of springing.

## Numbers and charts

- Counts, times and durations use `font-variant-numeric: tabular-nums`, so they do not jitter.
- Chart series pass 3:1 against their card in both themes; text passes 4.5:1.
- Each chart has a takeaway title, a direct label on the key value and a tap target per bar or
  point that shows the exact number. Only real numbers; never an invented trend.
