# AUT-1677 — company candidate source contract

Prepared against main `4d623da` and strike `9223887`; no provider or Companies storage/API/UI is activated.

`prospect_company_profile.py` defines an explicit `company-profile/1` candidate request/result for a future admitted profile step. It never renames a person's city or team size into company location/headcount. Name, industry, city and size must be literal business-scoped phrases with native prospect quotes/times. Each attribute quote must name the business. Size keeps its literal bounds/approximation/unit text; no numerical conversion or inferred employee count. Missing name means no candidate; missing attributes remain absent/Unknown. Old C5 without evidenced sales purpose/prospect roles admits no request.

The parser checks C5/C2 hash/revision, company output revision, known field keys, exact literal value/quote/native timing/prospect speaker and business-subject mention; contacts, person/identity keys, numeric conversions, duplicate JSON, oversized results and stale/misbound sources reject. It returns a source-pinned candidate without creating, matching, merging, linking or editing identities. These structural/literal checks do not prove every semantic business-property relationship: the admitted pack still needs subject-attribution validation and provider/professional/governance gates.

Twenty-one synthetic company tests and the existing nineteen bounded prospect-profile tests pass (40 combined), along with focused ruff and strict module mypy. Tests use no external request, private corpus words or database write.

Remaining: an approved capped profile request/provider pack and worker admission, separate durable company identity/append-only revisions/person links, list/profile and actual dev proof. The future writer must recheck source/access/withholding at commit, preserve human locks/history and never merge names. The current migration slot belongs to Strike C #421. Company/Pulse mapping is documented in `/home/acdev/strikes/pulse-people-roles.md` Mode B; it is conceptual, not a connector.
