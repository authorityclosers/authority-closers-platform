# AUT-1127: invoice total GST wording

Source: latest-main `a9b8fad8612897bc4729e3191dbc2ba97df11d26`, claimed through
`ac-gate start billing 1127-invoice-total-gst` after billing reported FREE.

The invoice renderer now prints `Total includes GST` where it previously printed
`Price includes GST`. The existing condition (saved taxable value plus saved GST
equals saved total) and all amount/rate rendering remain unchanged. This avoids
describing an Organisation/Enterprise base price as GST-inclusive.

The focused tests assert the exact paragraph, absence of the former wording,
and complete literal amount rows for these fictional immutable snapshots:

| Plan | Seats | Taxable value | Tax breakdown | Total |
| --- | --- | --- | --- | --- |
| Personal | 1 | INR 2,117.80 | CGST 9% INR 190.60; SGST 9% INR 190.60 | INR 2,499.00 |
| Organisation | 3 | INR 1,000.00 | IGST 18% INR 180.00 | INR 1,180.00 |
| Enterprise | 50 | INR 10,000.00 | CGST 9% INR 900.00; SGST 9% INR 900.00 | INR 11,800.00 |

Existing hostile-text escaping, invoice metadata, and saved historical 5% rate
coverage also pass. These amounts are fictional render fixtures, not catalogue
or settings changes.

Local development verification on 4 October 2026 (all exit 0):

- `uv run ruff format --check packages/python tests`: 957 files formatted.
- `uv run ruff check packages/python tests`: all checks passed.
- `uv run mypy packages/python`: no issues in 397 source files.
- `uv run pytest tests/unit/billing/test_invoice_render.py -q`: 5 passed.
- `ac-gate check`: task branch may be worked on.

To check on dev, run the focused pytest command above. After the approved change
ships through the normal release path, download a fictional buyer's invoice and
confirm `Total includes GST`, the saved amount rows, and the print view on dev,
then staging. Deployed verification remains for that post-release stage; these
local checks make no deployed or legal-compliance claim.
