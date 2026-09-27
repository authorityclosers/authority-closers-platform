# Versioned engine and report-language controls

Local candidate, 23 September 2026. Requires matching processing-plan integration
before deployment; adding these settings alone does not activate the new engine.

The existing append-only Admin authority now stores a report prompt selection
(`coaching-v3` or `coaching-v4`) and default report language (`en`, `hi-Deva+en`,
`mr-Deva+en`). Hindi/Marathi require v4. App controls remain English. The API,
Admin panel, history and CLI use the same typed service. CLI save flags are
`--c5-coaching-prompt-revision` and `--report-language-default`; read actions reject
mutation flags. Displayed options come from the server's capability bounds.

Migration 0044 adds constant legacy defaults without UPDATE/DELETE of historical
rows. Legacy command serialization omits unchanged new defaults, preserving
old receipt fingerprints. An old client cannot silently reset an existing v4
configuration by omitting the new controls. An explicit rollback creates a new
revision. Timestamps are projected in UTC so immediate and replayed responses
describe the same revision consistently across database session timezones.

Validation: 20 settings/CLI unit checks and two PostgreSQL integration scenarios
passed; five Admin component checks passed. Database coverage includes save/read,
legacy replay after a new revision, v4 replay, omission refusal, explicit rollback,
history preservation and no extra commands on reads/replay. Frontend checks cover
older server capability fallback, invalid language/engine rejection and the exact
saved selection. Targeted mypy, Ruff, Admin TypeScript and ESLint passed.

These are configuration/compatibility checks. They do not prove multilingual
report quality, production activation, or the completed public language picker.
