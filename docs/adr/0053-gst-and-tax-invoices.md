# ADR 0053: GST and immutable tax documents

Date: 3 October 2026. Task: AUT-878. CTO review and CEO approval required.

Amounts are integer paise at 1800 basis points, rounded half-up once on the
invoice total. Personal catalogue prices include GST; Organisation/Enterprise
prices add GST. Following the CTO amendment on AUT-878, checkout reads
`plans.prices_include_gst`, copies it into the immutable order/subscription,
and historical views and invoices use that copy rather than a plan-key mapping.

Verified matched settlement issues one invoice per provider/payment reference
in the same transaction as the period, lots and payment status. State-only,
rejected and mismatched provider events produce no invoice. Invoice dates use
the verification clock; financial years change on 1 April in Asia/Kolkata.
One immutable counter row per year is locked with `SELECT FOR UPDATE`; each
series takes MAX(sequence) + 1 under that lock. Rollback consumes no number.
Invoices use `<prefix>/<2627>/<sequence:05d>`; credit notes use
`<prefix>-CN/<2627>/<sequence:05d>` with an independent sequence. The prefix
defaults to `EA` and accepts 1–2 uppercase letters/digits. Numbers are unique
per financial year, use only letters/digits/`-`/`/`, and fit 16 characters.

Checkout snapshots the supplied buyer name, optional GSTIN and state. When
omitted, the name comes from the signed-in person's display name or the
organisation tenant name; missing names are marked pending. Buyer changes are
part of the checkout idempotency digest. Omitted buyer data preserves older
idempotency digests. No personal data is sent to a payment provider by this
addition. Seller legal name, GSTIN, registered address, state, SAC and prefix
come from settings; this change does not configure any environment. Missing
GSTIN/SAC remain explicitly pending; no tax classification is selected here.

Documents freeze seller, buyer, total/tax components and the sold plan/seats.
Currency, taxable value, CGST, SGST, IGST, total and place of supply are typed
columns; JSON holds seller/buyer/plan text. Checks require nonnegative INR
amounts, a balanced total, and mutually exclusive IGST versus CGST/SGST.
Known differing buyer/seller states use IGST. Matching or unknown states use
CGST = GST // 2 and SGST = GST - CGST. A full verified refund issues exactly one
credit note against the original invoice, copying its tax and party snapshot.
An intent, timeout, failed refund or correlation mismatch produces no note.

All four new tables reject UPDATE/DELETE. Corrections append rows with
`supersedes_id`; partial unique indexes retain one original row per payment,
refund or order, and unique supersession links prevent branching history.
These documents never determine access or change capacity accounting.
Migration 0069 is forward-only and extends restore parity to v41. Personal
name/GSTIN/state snapshots are inventoried. Listing and escaped print-ready
HTML are the next PR C; e-invoicing and PDF dependencies remain out of scope.
