# Seller Home: spec (Dipak's design, block by block, and the build)

Source: the Home polish studio's side-by-side, 4 Nov 2026. It was written from the orchestrator's text description of
Dipak's phone screenshot, because the image file could not be passed on. The left column is Dipak's design as described;
the middle column is what was built (dev, release v1.39.0 and the studio's later polish). Sizes snap to the app's type
scale. Font: Plus Jakarta, medium (500) throughout, as he draws it.

| # | Dipak's design (as described) | Built | Difference |
|---|---|---|---|
| 1 | Workspace name in small grey CAPS, "Home" large and medium; teal outlined +, search and bell as thin black line icons; hairline under the header | "FICTIONAL HOMES" 11 px grey capitals, "Home" 22 px / 500, an outlined teal + (32 px ring in a 44 px target), ink search at 1.75 stroke, an always-on hairline | The org's logo tile ("FH") stays before the name, and the avatar (opens You) stays at the left. The bell is the app's own component, unchanged (grey). |
| 2 | "Pending action" mint card, radius ~16; title ~18 medium; peach pill "1 reminder" (brown text); "<lead name> · Last dialled 2 hours ago"; teal "Complete call activity >" | Same blocks and words: the lead's real name, "Last dialled <ago>", "N reminder(s)". Shown only while a call waits for its answer. Tapping the row opens the call's question on Leads. | Title 16 px (his ~18, snapped to the scale). Calls put away with "Didn't call" on Leads stay away here. |
| 3 | Segmented control, grey pill track, white thumb on the selected side, ink and grey labels, ~48 dp | 48 dp, grey track, white sliding thumb, "Inbound Leads" / "Cold Leads", medium weight | None. The line under it ("Your assigned inbound enquiries") is removed. |
| 4 | "Today's overview" ~26 px regular/medium, "Your inbound lead activity" small grey under it | 28 px / 500 (snapped); "Your inbound lead activity" or "Your cold lead activity" at 14 px grey | Size snapped from 26 to 28. |
| 5 | 2 × 2 white tiles, 1 px light-grey border, radius ~14, no shadow; grey label, ~32 px medium two-digit number, small grey caption: New leads 02 First call pending / Open leads 02 Needs discussion / Follow-ups 02 Due today / Tasks 00 Due today | Exactly that: border 1 px, radius 14, no shadow, 32 px / 500 two-digit figures (02, 00; 12 and 229 as they are) and his words | On Cold the first tile keeps "Unworked leads / Never attempted". A failed read shows "–", never 0. |
| 6 | "Next action" white card with a light border, radius ~16; ~20 px title; green-tint pill "Ready to call"; name ~30 px medium; grey line "Added manually · Open lead"; full-width teal pill ~56 dp, phone icon, white "Call now" | Same card and words; the grey line is the lead's real source · status | Title 22 (his ~20) and name 28 (his ~30), both snapped. The Call fill is a deeper teal (7:1 for sunlight). Cold says "Start Cold Calling"; a missed call says "Call back". Holding the card offers Call, Open lead and Later, as on Leads. |
| 7 | "Today's tasks" ~20 px medium with teal "See all →"; light grey task cards, no border, radius ~12; medium title with a peach "Overdue" pill; grey "Call scheduled · 11:30 AM" | 22 px title (snapped), "See all →"; grey cards, radius 12, no border; Overdue pill when late | Each task keeps its done checkbox (one tap). The grey line reads time · type · lead ("11:30 AM · Inbound · Name"), because the app has no "Call scheduled" wording for a task. + Add is gone here (the owner's My tasks keeps it). |
| 8 | White bottom bar with a hairline top; five line icons with labels; Home active in ink; Ask Dipak a person line icon; the others grey | Docked white bar, hairline top, Home in ink, the rest grey, no capsule; Ask Dipak drawn as a person line icon | Leads keeps its real count badge when leads wait. |

## Beyond his first screen (unchanged, in their places)

- On Cold, the row "N fresh inbound leads need attention" sits under the control (from his earlier handoff).
- Below the fold: Upcoming follow-ups, Recent calls and Today's performance.
- On a sandbox organisation, the sandbox card closes the page.

## Call position

- In every seller case, the Call sits above the tab bar.
- In the busiest case (revenue line, pending call, Cold with its alert row), the page scrolls and the Call scrolls fully clear of the bar.
- At the app's 200 % text, every word wraps and nothing clips.

## Shell, every page (phones)

The restyle is CSS only, and every element stays in place:
- **Header:** grey capitals for the workspace, a medium title, an outlined +, and a hairline.
- **Tab bar:** docked, with the current tab in ink.

Leads reuses this header, the Inbound | Cold control, the card and the Call (see `../leads/spec.md`).
