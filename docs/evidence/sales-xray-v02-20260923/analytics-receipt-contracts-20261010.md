# AUT-1002: completed-receipt activity response contracts

Scope: [CTO plan revision cd081fba-610d-4f71-8858-f9e9e3017323](/AUT/issues/AUT-1002#document-plan). Branch `task/api/1002-analytics`, base `4d623dab8d6c78b0e261090d5df990eb904b5ee1`. Implementation commit: `3a8cda5a594d3e5902d025b388f335b34f5852fa`. The final PR head, including this evidence commit, is recorded on [AUT-1002](/AUT/issues/AUT-1002) and its PR work product.

Organisation authority: [settled Slice A plan](/AUT/issues/AUT-1391#document-plan), revision `e3cf7141-bf97-435a-9755-341d847e3c4d`, and [PR #370](https://github.com/authorityclosers/authority-closers-platform/pull/370), merge `bc61dbfaca369ee81f22a1e4097a5783a12d71a2`. Personal compatibility comes from `account_activity` at the pinned base. These reads describe **completed analysis usage**, counted from completed settlement receipts and charged seconds. They do not describe total recorded calls or sales performance.

## Implementation and compatibility

`AccountAcquisitionActivity` and `OrganisationAcquisitionActivity` validate the assembled dictionaries, then serialize back to the same JSON field sets and values. `CompletedReceiptDay` and `CompletedReceiptPerson` define nested field boundaries. Every field is required; extras and scalar coercion are rejected. Calendar dates retain their ISO string values; person IDs retain their canonical lowercase UUID string values. No missing measurement receives a default.

Both contracts require exactly 30 consecutive, ascending dates and `Asia/Kolkata`; the current response count equals the sum of day counts. Organisation people are unique and sorted by name/person ID; current and previous counts match the people sums, and current seconds match the sum of day seconds. These relational constraints run in model validators. Standard JSON Schema does not express sums or this relative date/name ordering; the exported model descriptions and this paragraph document them. Runtime strict validation also rejects numeric strings, booleans and floating-point measurements instead of coercing them; a generic JSON Schema validator alone does not reproduce all Python strict-type behavior. Date `format` requires a format-aware consumer, while the executable validator checks calendar validity.

Only response assembly validation/serialization changed in the projection file. SQL, admission calls, live owner/admin authority, IST windows, receipt attribution, display-name/masked-email policy, former-owner history and zero-filled dates remain intact. No HTTP route/OpenAPI wiring, metric, data write, migration or web change was added. [PR #421](https://github.com/authorityclosers/authority-closers-platform/pull/421) retains the HTTP route file.

## Checks and results

Before edits: `ac_task.py status` identified this existing branch as free to continue, main green; `ac_task.py check` passed. The API checkout was clean. Open PRs #429, #424, #421 and #412 did not overlap any of the five allowed paths. The platform checkout was not changed.

Final commands from the established API checkout:

```bash
uv run pytest tests/unit/conversation_intelligence/test_acquisition_activity_contracts.py tests/database/test_conversation_acquisition_activity_postgresql.py tests/unit/http/test_conversation_acquisition_activity_route.py tests/integration/test_organisation_activity_postgresql.py tests/unit/http/test_organisation_activity.py -q
uv run ruff format --check packages/python/ac_platform/conversation_intelligence/acquisition_activity_contracts.py packages/python/ac_platform/conversation_intelligence/acquisition_activity.py tests/unit/conversation_intelligence/test_acquisition_activity_contracts.py tests/database/test_conversation_acquisition_activity_postgresql.py
uv run ruff check packages/python/ac_platform/conversation_intelligence/acquisition_activity_contracts.py packages/python/ac_platform/conversation_intelligence/acquisition_activity.py tests/unit/conversation_intelligence/test_acquisition_activity_contracts.py tests/database/test_conversation_acquisition_activity_postgresql.py
uv run mypy packages/python/ac_platform/conversation_intelligence/acquisition_activity_contracts.py packages/python/ac_platform/conversation_intelligence/acquisition_activity.py
git diff --check
```

- **80 passed in 68.59 seconds; zero skips.** PostgreSQL used the run-injected disposable loopback harness with isolated schemas and fictional records. No application/production data was used.
- Complete populated/empty database responses round-trip through their named contracts without field or value changes. Added personal/organisation previous-only database cases also round-trip through dictionary and JSON validation, preserving zero current days and nonzero previous history.
- Unit checks reject every missing field, extras at every level, wrong measurement types, negative measurements, invalid dates/UUID strings, wrong day counts/order, inconsistent totals, duplicate people and incorrect person ordering. Named schemas retain the exact required field sets and constraints. Standalone final contract run: **61 passed**.
- Existing database proofs preserve one grouped receipt SELECT plus fixed admission overhead, live owner/admin and demotion checks, claimed/unclaimed/foreign/canary attribution, masked names and former-owner history. HTTP regressions preserve existing 401/403, private/no-store, Cookie headers, selected workspace, shared identity locks, query rejection and POST 405 behavior. Retained organisation database/HTTP checks pass.
- Format: four files already formatted. Ruff lint: passed. Mypy: no issues in the two changed source files. Diff whitespace: passed. An initial mypy inference failure after extracting the response variable was corrected with an explicit `dict[str, Any]` annotation; the final checks above passed.
- Remote CI has not yet been checked in this receipt. Its result must be recorded at the final PR SHA through the PR/watchdog path; local results are not a claim that remote checks or deployment have passed.

## Actual dev inspection and limits

Before edits on 10 October 2026, unauthenticated GETs at `https://salesxray-dev.authorityclosers.com/v1/conversation/acquisition/activity` and `/v1/conversation/acquisition/organisation/activity` each returned **HTTP 302**. No approved fictional session was injected, and the current run's granted-secret metadata returned an empty list. Authenticated dev before/after behavior is **not verified**. This branch has not been deployed; the disposable database/ASGI checks above are local evidence.

After governed delivery, use an approved fictional session on that dev origin: GET personal activity, then select its organisation and GET organisation activity as owner/admin; compare exact JSON fields and values with known completed receipts. Repeat empty and previous-only fixtures and member/ex-admin rejection. Do not create sessions or change memberships manually. Record the actual deployed version and resulting checks on the delivery task.

Independent CTO code review is required at the exact PR SHA. No merge/deploy/activation is claimed. [AUT-1616](/AUT/issues/AUT-1616) retains UI wiring and [AUT-1392](/AUT/issues/AUT-1392) retains route delivery verification; neither was recreated or added as a lane blocker. E10 delivery remains open until governed production-version evidence is complete.

## Exported schemas

These are unedited `model_json_schema()` outputs from the same executable contracts at the implementation commit. Reproduce with:

```python
import json
from ac_platform.conversation_intelligence.acquisition_activity_contracts import (
    AccountAcquisitionActivity,
    OrganisationAcquisitionActivity,
)
for contract in (AccountAcquisitionActivity, OrganisationAcquisitionActivity):
    print(json.dumps(contract.model_json_schema(), indent=2, sort_keys=True))
```

### AccountAcquisitionActivity

```json
{
  "$defs": {
    "CompletedReceiptDay": {
      "additionalProperties": false,
      "properties": {
        "analysed": {
          "minimum": 0,
          "title": "Analysed",
          "type": "integer"
        },
        "analysed_seconds": {
          "minimum": 0,
          "title": "Analysed Seconds",
          "type": "integer"
        },
        "date": {
          "format": "date",
          "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
          "title": "Date",
          "type": "string"
        }
      },
      "required": [
        "date",
        "analysed",
        "analysed_seconds"
      ],
      "title": "CompletedReceiptDay",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "description": "Thirty consecutive IST dates; current count equals the sum of day counts.",
  "properties": {
    "analysed_last_30_days": {
      "minimum": 0,
      "title": "Analysed Last 30 Days",
      "type": "integer"
    },
    "analysed_previous_30_days": {
      "minimum": 0,
      "title": "Analysed Previous 30 Days",
      "type": "integer"
    },
    "days": {
      "items": {
        "$ref": "#/$defs/CompletedReceiptDay"
      },
      "maxItems": 30,
      "minItems": 30,
      "title": "Days",
      "type": "array"
    },
    "timezone": {
      "const": "Asia/Kolkata",
      "title": "Timezone",
      "type": "string"
    }
  },
  "required": [
    "timezone",
    "days",
    "analysed_last_30_days",
    "analysed_previous_30_days"
  ],
  "title": "AccountAcquisitionActivity",
  "type": "object"
}
```

### OrganisationAcquisitionActivity

```json
{
  "$defs": {
    "CompletedReceiptDay": {
      "additionalProperties": false,
      "properties": {
        "analysed": {
          "minimum": 0,
          "title": "Analysed",
          "type": "integer"
        },
        "analysed_seconds": {
          "minimum": 0,
          "title": "Analysed Seconds",
          "type": "integer"
        },
        "date": {
          "format": "date",
          "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
          "title": "Date",
          "type": "string"
        }
      },
      "required": [
        "date",
        "analysed",
        "analysed_seconds"
      ],
      "title": "CompletedReceiptDay",
      "type": "object"
    },
    "CompletedReceiptPerson": {
      "additionalProperties": false,
      "properties": {
        "analysed_last_30_days": {
          "minimum": 0,
          "title": "Analysed Last 30 Days",
          "type": "integer"
        },
        "analysed_previous_30_days": {
          "minimum": 0,
          "title": "Analysed Previous 30 Days",
          "type": "integer"
        },
        "analysed_seconds_last_30_days": {
          "minimum": 0,
          "title": "Analysed Seconds Last 30 Days",
          "type": "integer"
        },
        "name": {
          "title": "Name",
          "type": "string"
        },
        "person_id": {
          "format": "uuid",
          "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
          "title": "Person Id",
          "type": "string"
        }
      },
      "required": [
        "person_id",
        "name",
        "analysed_last_30_days",
        "analysed_seconds_last_30_days",
        "analysed_previous_30_days"
      ],
      "title": "CompletedReceiptPerson",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "description": "Unique people sorted by name/ID; people totals equal day and response totals.",
  "properties": {
    "analysed_last_30_days": {
      "minimum": 0,
      "title": "Analysed Last 30 Days",
      "type": "integer"
    },
    "analysed_previous_30_days": {
      "minimum": 0,
      "title": "Analysed Previous 30 Days",
      "type": "integer"
    },
    "days": {
      "items": {
        "$ref": "#/$defs/CompletedReceiptDay"
      },
      "maxItems": 30,
      "minItems": 30,
      "title": "Days",
      "type": "array"
    },
    "people": {
      "items": {
        "$ref": "#/$defs/CompletedReceiptPerson"
      },
      "title": "People",
      "type": "array"
    },
    "timezone": {
      "const": "Asia/Kolkata",
      "title": "Timezone",
      "type": "string"
    }
  },
  "required": [
    "timezone",
    "days",
    "analysed_last_30_days",
    "analysed_previous_30_days",
    "people"
  ],
  "title": "OrganisationAcquisitionActivity",
  "type": "object"
}
```
