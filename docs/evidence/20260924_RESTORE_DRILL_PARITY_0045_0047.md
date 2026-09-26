# Restore-drill parity contracts for migrations 0045–0047

Migrations `20260923_0045` and `20260923_0046` add `email_login_codes` and
`sales_xray_profiles`, respectively. The reviewed parity inventories therefore
advance from 98 tables at `20260923_0044` to 99 and then 100 tables. Migration
`20260924_0047` changes check constraints on the existing
`conversation_analysis_settings` table; it adds no table, so its inventory
remains at 100 tables.

The backup writer, restic restore-proof controller, and application restore
drill now share exact versioned mappings: `ac-postgres-parity-v25` for 0045,
`ac-postgres-parity-v26` for 0046, and `ac-postgres-parity-v27` for 0047.
Contracts v2–v24 and their inventories are preserved. Unknown migration heads
remain fail-closed. Tests compare all three catalogues, inspect the checked-in
migrations for their actual created tables, and validate source metadata and
restored row-count parity for versioned heads.

Validation on Windows completed with 1,637 focused backup-parity and
restore-drill tests passing and 2 integration-only checks skipped (Docker
daemon unavailable; explicit restore-drill opt-in requires an approved dump).
Ruff passed for all five changed Python files. No database or provider was
used.
