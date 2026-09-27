# Sales X-Ray prospect fact contract implementation evidence

This change adds a provider-free, immutable domain contract for source-supported
fact values. It is a reusable fidelity foundation only: it does not create a
Prospects feature, extract facts, authorize a caller, persist private content,
or activate CRM, retention, sharing, or provider behavior.

The contract preserves numeric interval shape and endpoint inclusivity separately
from approximation; retains currency, unit, scale, period, period reference,
component, cadence, and tax treatment as separate caller-provided values; makes
unknown explicit; and permits multiple source supports, each tied to a source
lifecycle ID and source revision ID/number. Fact revisions are immutable, and a
successor must link to the immediately prior revision. Text is never truncated
or normalized; invalid values raise content-free validation codes. Numeric
values outside the represented decimal precision are rejected without rounding.

This implementation intentionally leaves source ownership/authorization,
retention and erasure, entity relationships, fact taxonomy, extraction,
transport, persistence, and runtime activation to later controlled decisions.
All tests use synthetic values and do not call providers or access live data.

Files:

- `packages/python/ac_platform/conversation_intelligence/prospect_fact_contract.py`
- `tests/unit/conversation_intelligence/test_prospect_fact_contract.py`

Focused verification command:

```powershell
uv run pytest tests/unit/conversation_intelligence/test_prospect_fact_contract.py
```

Additional static checks:

```powershell
uv run ruff check packages/python/ac_platform/conversation_intelligence/prospect_fact_contract.py tests/unit/conversation_intelligence/test_prospect_fact_contract.py
uv run mypy packages/python/ac_platform/conversation_intelligence/prospect_fact_contract.py
```
