# Sales authentication integration — 13 September 2026

Sources38e5e8d7e62509a74d9e775d739b13a000cea728 and15a8ee8e05c32ff3accb7ee21976dd8212d1384a are integrated as a466b14 and3f6dd80.

The worker conflict was resolved by keeping the class method delegated to the shared canonical password-message resolver. That resolver explicitly accepts V1, course-context V2, and Sales-context V3 jobs; only V3 adds the allowlisted /sales-xray continuation. The initial-held verification bootstrap remains exact V1. Media and conversation worker composition are preserved.

Validation on the combined tree:175 worker/outbox/bootstrap and Sales-auth HTTP tests passed. Changed worker Ruff lint/format and mypy passed. This is integration evidence; hosted Sales browser acceptance and the immutable combined release are still pending.
