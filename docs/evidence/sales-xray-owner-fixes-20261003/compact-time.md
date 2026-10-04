# AUT-992 E0: compact analysis time

Source base: `cf15c61b` (includes merged speaker wiring PR #273).

The phone and laptop shell pills show hours above 60 minutes, rounded down so the compact label never overstates the available time. A 10,000-minute allowance reads `166 h`; 60 minutes stays `60 min`. Tooltips and accessible meter values retain the exact minute totals and seconds. The percentage ring still uses the verified allowance. The account menu uses the same compact time and no longer infers Trial or Unlimited plan names from an allowance flag. New-analysis footer copy also uses hours for long balances.

Legacy internal tester responses do not contain a finite available balance. Their pills and menu now say `Time unavailable`, with no infinity symbol, invented zero balance, full meter or plan claim. This changes display only; a backend flag is not a credit balance.

Implementation choice: ship this independent time-display prerequisite while E1 supplies the canonical credit-balance HTTP read. Credits and minutes are separate currencies. PR #262 adds internal ledger reads only; AUT-993's plan explicitly defers HTTP balance/history. This PR supplies no synthetic credit balance and does not complete the full credits-and-hours requirement. Other account, billing, organisation and plans surfaces remain for subsequent E0/E1 slices.

## Verification

- Web lint and typecheck passed.
- Final changed-area suite: 29 passed across time formatter, shell, footer, menu and profile menu. New-analysis formatter checks: 4 passed, 105 unrelated tests excluded by name.
- Browser checks at 390 and 1440 px: both actual pill components show `166 h`, exact accessible seconds/minutes and percentage are retained, 60-minute boundary stays in minutes, legacy balance has no finite meter or Unlimited claim, zero page errors and horizontal overflow. The temporary preview server was stopped.
- [Phone](time-pill-390.png), [laptop](time-pill-1440.png), [browser receipt](time-pill-browser.json).

Browser screenshots use actual branch components and application CSS in a clearly labelled fictional component preview. They do not prove deployed account balances or credit persistence. No recordings, real accounts or provider calls were used.

## Dev check after merge

At https://salesxray-dev.authorityclosers.com, open a fictional sandbox account with a finite allowance at 390 px and laptop width. Check the header pill, account menu and New analysis footer. An available 10,000-minute allowance shows `166 h`; 60 minutes shows `60 min`. Hover the laptop pill or inspect its accessible meter to see exact totals; confirm the percentage still matches the server response. A legacy tester response should show `Time unavailable`, not a plan name or finite balance. Repeat on staging after the train deploys.

Limits: authenticated dev saves and staging verification remain pending. The read-only dev fixture at 390 px still showed local-save copy after PR #273 merged; it is not proof of the live speaker provider. Existing loopback shells at ports 3016/3026 served older pill copy during this run; their owning checkouts were not altered. Paperclip reports no realized execution workspace for this issue, so the bounded component preview used a run-owned scratch directory and synchronous server teardown.

## Speaker continuation

The watchdog merged PR #273 at approved head `4a38995`, producing main `cf15c61b`. The focused speaker rerun on merged main passed: 24 tests. Authenticated dev save verification remains pending; a fixture rendering local-save copy does not verify the live server provider.

Keep E0 open. Server-backed credit display requires the E1 balance contract; facts/promise persistence, remaining Unlimited labels and the other owner-seen fixes are unfinished.
