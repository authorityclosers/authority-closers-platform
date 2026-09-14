# Campaign quota and cost audit

Read-only source review against c437 and Cloudflare API reads on 2026-09-14.
This records findings; it does not grant minutes, raise budgets or activate a provider.

## Implemented controls

- The controlled trial is 6,000 seconds (100 minutes), shared across a guest and
  the canonical account to which that guest is claimed. The source is
  `acquisition_usage.py` and `acquisition_sessions.py`; the initial allowance is
  recorded in `docs/releases/V0_2_RELEASE_CONSOLIDATION.md` and
  `docs/contracts/SALES_XRAY_GUEST_PROCESSING_V1.md`.
- Server-measured duration, locked reservations, same-person claim replay and
  confirmed-no-work releases prevent an ordinary retry/signup allowance reset.
  New visitor/person identities can still receive separate trials. This is not
  proof of one unique human across accounts or devices.
- Turnstile checks exact hostname, action and token age. Session issuance has a
  process-local trusted-edge-IP limit of five POSTs in 900 seconds. This is not
  a distributed IP limit or a VPN block.
- Shared provider budget reservations and uncertain-work holds exist. New guest
  provisioning itself creates no funded provider budget or minute grants.
- The personalized UI follow-up keeps exact remaining minutes and seconds visible
  after submission. A UI readout does not replace server entitlement enforcement.

## Fresh edge observation

Both Sales Xray DNS records were proxied on the Free Website plan. The zone
ruleset listing returned managed normalization, Free WAF and DDoS L7 rulesets;
no custom firewall or HTTP rate-limit entrypoint was listed. No edge changes
were made. Cloudflare's managed VPN IP list requires Enterprise, so current
proxying must not be described as VPN blocking.

Actual filtered API receipts:
`D:/AC-authority-closers-release-audit/personal-report-20260914/cloudflare-zone-read.json`
and `cloudflare-rules-read.json` in the same directory. These omit origin targets
and credentials. Provider documentation:
https://developers.cloudflare.com/waf/tools/lists/managed-lists/

## INR10,000 for 100 students

The target permits an average INR100 per student. It is not yet a measured result.
The bounded activation packet is INR100 staging plus INR900 production; it is
separate from a funded campaign budget and does not authorize automatic purchases.

The current conservative processing-plan envelope is INR11 for C2, up to
16 C4 requests at INR5 each, and INR5 for C5: at most INR96 per plan. These are
reservation ceilings, not measured provider charges, and do not cover arbitrary
retries or repeated plans. One such plan for each of 100 students reserves at most
INR9,600, leaving INR400. This calculation must not be advertised as the cost of
every student's entire 100-minute entitlement.

One hundred students using 100 minutes each is 10,000 source minutes (166h40m).
The 30-minute upload cap means a fully used allowance can span at least four calls;
many short calls can incur still more per-plan overhead. Four maximally reserved
plans per student would reserve INR38,400. Actual charges can be far lower, but
only observed input/output usage, provider billing and reconciled reservations can
establish that. No campaign-wide INR10,000 enforcement was verified by this audit.

Before a campaign capacity claim, the release owner must bind the finite campaign
grant and shared spending ceiling into the deployed authority configuration,
exercise concurrent/exhausted/retry paths and reconcile real provider usage.
This does not require inventing a new trial-minute allotment.

## Evidence limits

Existing disposable tests cover guest claim, retry and allowance isolation.
The audit's fresh unit run reported 59 passes and one Windows file-permission
failure; a PostgreSQL rerun had setup errors without a disposable database URL.
Neither is presented as a successful hosted test. Current live activation and its
real recording receipts belong to the release task. No provider calls, grants,
database writes, Cloudflare mutations or credit purchases were made by this audit.
