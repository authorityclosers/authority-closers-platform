# Provisional controlled-source gaps

No item below authorizes an engineer to invent business behavior. The temporary implementation seam must remain replaceable and must not activate an irreversible provider dependency.

| Gap | Temporary implementation rule | Owner / close condition |
|---|---|---|
| Permanent auth state/component IDs | Prefix implementation-only identifiers with `PROV-AUTH`; do not export as analytics taxonomy | Product/UX controlled-doc update |
| Exact OAuth route and claim contract | Implement provider port and fake assertion only; production provider binding remains disabled | Security/API approval plus real callback URL |
| Completion/certificate component IDs | Use semantic internal names, not fabricated controlled IDs | UI/UX controlled-doc update |
| Exact draft/evidence route schemas | Version `/v1`; keep schema fields minimal and document every revision | API/SRS reconciliation |
| Certificate/recovery/frozen-state entity IDs | Use stable internal class/table names with `contract_status=provisional` evidence note | Data-model controlled-doc update |
| Audit event classification catalogue | Permit bounded G1 names only; never send audit payload through analytics | Security/telemetry reconciliation |
| Formal G1/G2 declaration | Build and measure against proposed gate; do not claim controlled G1 pass | ADR-025 promotion/supersession |
| Exact free-course copy and media | Seed only founder-approved, source-cited content; otherwise render honest empty state | Content approval record |

Review date: before any staging cohort release.
