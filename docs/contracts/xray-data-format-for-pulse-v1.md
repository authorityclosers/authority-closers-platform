# X-Ray data format for Pulse, v1 (draft for agreement)

**Status: DRAFT, 6 Nov 2026. Not agreed by AC, Wise Life or Pulse.** Written from the code at release v1.39.0 (commit 8656044). Pulse's two working days start only once AC and Wise Life agree this (ceo-room msgs 120, 121). Agreeing it does not authorise real data; that still needs AC's business, data, security and release checks (msg 121).

Every example below is the real output of Sales X-Ray staging on 6 Nov 2026, from fictional calls, a fictional organisation and fictional leads. Some long lists are shortened and say so. Nothing in it is a real person.

## 1. The two ways X-Ray data leaves Sales X-Ray

| | Read API (`/v1/api`, and the MCP server `/v1/mcp` on the same reader) | Signed event (`sx.analysis_completed.v1`) |
|---|---|---|
| Who starts it | The other app asks | Sales X-Ray sends when a report is ready |
| Used by | Sales X-Ray inside Pulse (`docs/architecture/SALES_XRAY_IN_PULSE.md`): read live for the person on screen, never stored | A partner platform such as Wise Life's: call to quotation |
| Sign-in | A person's Connect token (`sxa_`) or an organisation key (`sxk_`), with scopes | HMAC-SHA256 signature |
| Carries transcript words | **Yes:** each fact's `evidence[].quote` is a transcript segment. Withheld segments are never quoted | **No.** Only short `stated_as` words and rewritten sentences |
| Carries a phone number | **Yes, on one lead:** lead lists give `phone_last4` with `phone` null, but `GET /v1/api/leads/{id}` gives the full `phone` and `email` | **Yes:** `lead.phone_e164`, when the call was uploaded on a lead |

Pulse's CTO should check the two "Yes" rows for the privacy review.

## 2. Read API field list

Errors are `{"error": {"code", "message"}}`. Scopes: `calls:read`, `reports:read`, `leads:read`. Reach: an organisation key sees what an owner sees; a person's token sees what that person sees, checked on every request.

**`GET /v1/api/calls?before=`** gives `calls[]` (newest first, 50 a page) and `next_before`.

| Field | Meaning |
|---|---|
| `id` | The call's id |
| `title` | Its title, or null |
| `created_at` | When it was uploaded |
| `duration_seconds` | Its length |
| `has_report` | Whether a report is ready |
| `open_url` | Where to open it in Sales X-Ray (the person must be signed in and a member) |

**`GET /v1/api/calls/{id}`** gives the same, plus `facts[]` when the token also has `reports:read`.

**`GET /v1/api/calls/{id}/facts`** (`prospect-facts/1`) gives `subject`, `taxonomy_version`, `pipelines` (`fast` and `deep`, each with `state` and `at`) and `facts[]`:

| Field | Meaning |
|---|---|
| `object_id` | The fact's id |
| `type`, `category`, `label`, `kind` | What kind of fact it is, from the call taxonomy |
| `value` | Its value; the shape depends on `kind` |
| `display` | One line to show |
| `confidence` | 0 to 1 |
| `basis` | `observed` or `inferred` |
| `status` | For example `kept`, `asked` |
| `ai_read` | True for an AI judgement, which must always be labelled as the AI's read |
| `evidence[]` | `segment_id`, `quote`, `start_ms`, `end_ms`, `speaker`, `role` |
| `call` | `recording_id`, `submission_id`, `at` |
| `source` | `pipeline`, `version`, `taxonomy_version` |
| `prospect_field` | The prospect field it feeds, when any |

**`GET /v1/api/leads/{id}`** gives one lead (`lead`, `phone`, `email`, `fields`, `events`, `tasks` and more). Its body was fetched on staging but is not reproduced here. **`GET /v1/api/leads?stage=&offset=`** (`lead-desk/1`) gives `leads[]`. The full list of fields is in the example below; the main ones are `lead_id`, `revision`, `name`, `company`, `city`, `language`, `interest`, `phone_last4`, `stage`, `stage_label`, `source`, `owner_person_id`, `owner_name`, `created_at`, `next_action_at`, `attempts`, `calls`, `test_data`.

### Fictional example: a call

```json
{
  "id": "5cea290d-e78f-438a-b307-9534b97a3f6b",
  "title": null,
  "created_at": "2026-11-06T10:42:15.818115+00:00",
  "duration_seconds": 92,
  "has_report": true,
  "open_url": "https://salesxray-staging.authorityclosers.com/analysis/calls/5cea290d-e78f-438a-b307-9534b97a3f6b",
  "facts": "(the same list as /calls/{id}/facts)"
}
```

### Fictional example: its facts (2 of its facts shown, 1 piece of evidence each)

```json
{
  "schema": "prospect-facts/1",
  "subject": {
    "kind": "call",
    "id": "5cea290d-e78f-438a-b307-9534b97a3f6b"
  },
  "taxonomy_version": "call-taxonomy/2",
  "pipelines": {
    "fast": {
      "state": "done",
      "at": "2026-11-06T10:42:54.543020+00:00"
    },
    "deep": {
      "state": "done",
      "at": "2026-11-06T10:43:15.035308+00:00"
    }
  },
  "facts": [
    {
      "object_id": "fd5144d3-7041-44ee-baf3-781b3145266b",
      "type": "commitment.follow_up",
      "category": "commitment",
      "label": "Next follow-up",
      "kind": "when",
      "value": {
        "text": "Saturday morning",
        "date": "2026-11-07",
        "purpose": "Site visit with brother present"
      },
      "display": "Saturday morning · Site visit with brother present",
      "confidence": 0.95,
      "basis": "observed",
      "status": "asked",
      "ai_read": false,
      "evidence": [
        {
          "segment_id": "s15",
          "quote": "I understand. I will send you the quotation today, and we can arrange a site visit on Saturday morning with your brother present.",
          "start_ms": 74880,
          "end_ms": 82000,
          "speaker": "speaker_0",
          "role": "salesperson"
        }
      ],
      "call": {
        "recording_id": "81f0db5b-7494-401c-b57d-c24c37af5551",
        "submission_id": "5cea290d-e78f-438a-b307-9534b97a3f6b",
        "at": "2026-11-06T10:43:15.035308+00:00"
      },
      "source": {
        "pipeline": "deep",
        "version": "deep/1",
        "taxonomy_version": "call-taxonomy/2"
      },
      "prospect_field": "next_step"
    },
    {
      "object_id": "5f651a82-b19a-4cbf-9581-ff769c8b4988",
      "type": "commitment.next_step",
      "category": "commitment",
      "label": "Next step",
      "kind": "text",
      "value": {
        "text": "Seller to send quotation today and conduct a site visit on Saturday morning"
      },
      "display": "Seller to send quotation today and conduct a site visit on Saturday morning",
      "confidence": 0.95,
      "basis": "inferred",
      "status": "kept",
      "ai_read": false,
      "evidence": [
        {
          "segment_id": "s15",
          "quote": "I understand. I will send you the quotation today, and we can arrange a site visit on Saturday morning with your brother present.",
          "start_ms": 74880,
          "end_ms": 82000,
          "speaker": "speaker_0",
          "role": "salesperson"
        }
      ],
      "call": {
        "recording_id": "81f0db5b-7494-401c-b57d-c24c37af5551",
        "submission_id": "5cea290d-e78f-438a-b307-9534b97a3f6b",
        "at": "2026-11-06T10:43:15.035308+00:00"
      },
      "source": {
        "pipeline": "deep",
        "version": "deep/1",
        "taxonomy_version": "call-taxonomy/2"
      },
      "prospect_field": null
    }
  ]
}
```

### Fictional example: a lead (1 of 3 shown)

```json
{
  "schema": "lead-desk/1",
  "leads": [
    {
      "lead_id": "855c41ce-aab7-479c-a905-567085954eef",
      "revision": 4,
      "name": "TEST Lead B WL-SYNTH",
      "company": "Example Traders",
      "city": "Nagpur",
      "language": "Hindi",
      "interest": "5 kW rooftop solar",
      "phone_last4": "0174",
      "phone": null,
      "stage": "won",
      "stage_label": "Won",
      "source": "manual",
      "source_label": "Added by hand",
      "owner_person_id": "42a09f0e-8f1f-423d-9631-561fcd8a927f",
      "owner_name": "TEST Owner WL-SYNTH",
      "owner_photo_url": null,
      "why": "Won",
      "why_kind": "closed",
      "next_action_at": null,
      "created_at": "2026-11-06T10:40:48.075924Z",
      "received_at": null,
      "attempts": 1,
      "calls": 0,
      "last_result": "won",
      "last_result_label": "Won",
      "test_data": false,
      "overdue": false,
      "step": "won",
      "pipeline": "main",
      "side": "inbound",
      "missed_at": null,
      "missed_calls": 0,
      "stage_at": "2026-11-06T10:47:09.703355Z",
      "group": "won",
      "outcome_reason": null,
      "outcome_reason_label": null,
      "last_contact_at": "2026-11-06T10:47:09.703355Z",
      "next_action_note": null,
      "no_next_action": false,
      "has_email": false
    }
  ],
  "total": 3,
  "next_offset": null,
  "stage_counts": {
    "new": 2,
    "won": 1
  },
  "step_counts": {},
  "owner_counts": {
    "42a09f0e-8f1f-423d-9631-561fcd8a927f": 2,
    "dfb42ac7-4c60-487d-a20e-9abee87cf2d6": 1
  },
  "view_counts": {},
  "stages": [
    {
      "key": "new",
      "label": "New Lead"
    },
    {
      "key": "open_leads",
      "label": "Open Leads"
    },
    {
      "key": "not_connected",
      "label": "Not Connected"
    },
    {
      "key": "interested",
      "label": "Interested"
    },
    {
      "key": "meeting_scheduled",
      "label": "Meeting Scheduled"
    },
    {
      "key": "meeting_done",
      "label": "Meeting Done"
    },
    {
      "key": "won",
      "label": "Won"
    },
    {
      "key": "lost",
      "label": "Closed / Lost"
    },
    {
      "key": "junk",
      "label": "Junk Lead"
    }
  ]
}
```

## 3. Signed event field list (`sx.analysis_completed.v1`)

Headers: `X-SX-Event-Id`, `X-SX-Event-Type`, `X-SX-Signature: t=<unix>,v1=<hex>[,v1=<hex>]`, where `v1 = HMAC-SHA256(secret, "<t>." + raw body)`. A second `v1` appears during a secret rotation. Reject anything older than 300 seconds. Any 2xx means delivered. Otherwise the same bytes are sent again after 10 s, doubling to 1 hour, 25 tries, then a dead letter. No redirects are followed.

| Field | Meaning |
|---|---|
| `schema`, `event_id`, `event_type`, `occurred_at` | The event |
| `tenant_ref` | `ten_` and the organisation id |
| `analysis_id`, `analysis_revision`, `supersedes_event_id` | `sub_` and the call id; a later revision names the event it replaces |
| `analysis_url` | Where to open the call |
| `call` | `uploaded_at`, `duration_sec`, `report_language` |
| `salesperson` | `ref`, `name`, `email` of the uploader |
| `lead` | `ref`, `phone_e164`, `name`, `city` of the lead the call was uploaded on, **or null when the call was not uploaded on a lead** |
| `summary` | At most 1,500 characters. Every number reads `[n]` |
| `outcome.kind` | `closed`, `follow_up`, `no_sale`, `future_date`, `disqualified`, `unclear`, or null |
| `extraction` | `profile`, `status` (`complete`, `failed`, `skipped`), `looked_for` |
| `facts[]` | Empty unless `extraction.status` is `complete`, which needs a facts profile on the webhook |

Each fact has `type`, `status` (`stated`, `conflicting`, `unknown`), `value`, `source` (`segment_id`, `t_start_sec`, `t_end_sec`, `speaker`) and, when conflicting, `alternatives[]`. One-per-call types always appear, as `unknown` when not said.

| Fact type | One per call | `value` |
|---|---|---|
| `system_size` | yes | `stated_as`, `quantity`, `unit` (`kW`, `kVA`) |
| `product_mention` | | `stated_as` |
| `load` | | `stated_as` |
| `add_on` | | `kind`, `qty`, `stated_as` |
| `battery_type` | yes | `kind` (`lithium`, `tubular`, `other`), `stated_as` |
| `warranty` | yes | `years`, `stated_as` |
| `site` | yes | `stated_as` |
| `delivery_basis` | yes | `kind` (`delivered_to_site`, `from_godown`), `stated_as` |
| `mentioned_price` | | `applies_to`, `speaker`, `stated_as`, `amount_inr`, `basis`, `use` (always `flag_only`) |
| `promise` | | `speaker`, `text` |
| `next_step` | | `action`, `when_text` |
| `objection` | | `kind`, `text` |

`add_on.kind`: dongle, packing, extended_warranty, acdb, dcdb, battery, panel, structure, earthing, lightning_arrestor, other. `next_step.action`: send_quotation, site_visit, call_back, meeting, other. `objection.kind`: price_concern, affordability_gap, time_constraint, stall, competitor_or_status_quo, decision_maker_absent, trust_concern, other.

### Fictional example (one fact of each of six types shown)

```json
{
  "analysis_id": "sub_5cea290de78f438ab3079534b97a3f6b",
  "analysis_revision": 1,
  "analysis_url": "https://salesxray-staging.authorityclosers.com/analysis/calls/5cea290d-e78f-438a-b307-9534b97a3f6b",
  "call": {
    "duration_sec": 91,
    "report_language": "en",
    "uploaded_at": "2026-11-06T10:42:16Z"
  },
  "event_id": "7827942a-43fd-4f57-a163-e15692521102",
  "event_type": "analysis.completed",
  "extraction": {
    "looked_for": [
      "system_size",
      "product_mention",
      "load",
      "add_on",
      "battery_type",
      "warranty",
      "site",
      "delivery_basis",
      "mentioned_price",
      "promise",
      "next_step",
      "objection"
    ],
    "profile": "rooftop-solar-quote-v1",
    "status": "complete"
  },
  "facts": [
    {
      "source": {
        "segment_id": "s5",
        "speaker": "unknown",
        "t_end_sec": 27,
        "t_start_sec": 20
      },
      "status": "stated",
      "type": "system_size",
      "value": {
        "quantity": null,
        "stated_as": "five-kilowatt",
        "unit": null
      }
    },
    {
      "source": {
        "segment_id": "s11",
        "speaker": "unknown",
        "t_end_sec": 60,
        "t_start_sec": 53
      },
      "status": "stated",
      "type": "add_on",
      "value": {
        "kind": "dongle",
        "qty": null,
        "stated_as": "dongle"
      }
    },
    {
      "source": {
        "segment_id": "s5",
        "speaker": "unknown",
        "t_end_sec": 27,
        "t_start_sec": 20
      },
      "status": "stated",
      "type": "battery_type",
      "value": {
        "kind": "lithium",
        "stated_as": "lithium"
      }
    },
    {
      "alternatives": [
        {
          "source": {
            "segment_id": "s9",
            "speaker": "unknown",
            "t_end_sec": 49,
            "t_start_sec": 39
          },
          "value": {
            "stated_as": "five-year",
            "years": 5
          }
        },
        {
          "source": {
            "segment_id": "s9",
            "speaker": "unknown",
            "t_end_sec": 49,
            "t_start_sec": 39
          },
          "value": {
            "stated_as": "five years",
            "years": 5
          }
        }
      ],
      "source": {
        "segment_id": "s9",
        "speaker": "unknown",
        "t_end_sec": 49,
        "t_start_sec": 39
      },
      "status": "conflicting",
      "type": "warranty",
      "value": {
        "stated_as": "twenty-five-year",
        "years": null
      }
    },
    {
      "source": {
        "segment_id": "s13",
        "speaker": "unknown",
        "t_end_sec": 71,
        "t_start_sec": 61
      },
      "status": "stated",
      "type": "mentioned_price",
      "value": {
        "amount_inr": 370000,
        "applies_to": "system",
        "basis": null,
        "speaker": "unknown",
        "stated_as": "three lakh seventy thousand rupees",
        "use": "flag_only"
      }
    },
    {
      "source": {
        "segment_id": "s15",
        "speaker": "unknown",
        "t_end_sec": 82,
        "t_start_sec": 74
      },
      "status": "stated",
      "type": "next_step",
      "value": {
        "action": "send_quotation",
        "when_text": "today"
      }
    }
  ],
  "lead": {
    "city": "Nagpur",
    "name": "TEST Lead B WL-SYNTH",
    "phone_e164": "+911100000174",
    "ref": "lead_855c41ceaab7479ca905567085954eef"
  },
  "occurred_at": "2026-11-06T10:43:16Z",
  "outcome": {
    "kind": "follow_up"
  },
  "salesperson": {
    "email": "s172.owner@wl-synth.example.test",
    "name": "TEST Owner WL-SYNTH",
    "ref": "per_42a09f0e8f1f423d9631561fcd8a927f"
  },
  "schema": "sx.analysis_completed.v1",
  "summary": "Riya conducted an initial scoping call with Kavya, assessed load requirements for a combined shop and home roof in Nagpur, recommended a [n] hybrid solar setup, and quoted approximately [n]. When Kavya expressed that this exceeded her planned budget and required her brother's agreement, Riya agreed to send the quote via WhatsApp and scheduled a joint site visit for Saturday morning.",
  "supersedes_event_id": null,
  "tenant_ref": "ten_2647496292fe4424921c8de45d22e2e8"
}
```

## 4. Other events

Lead events use the same headers and the same address as the call event, so a receiver must read `X-SX-Event-Type`. Schema `sx.lead_event.v1`: `lead.created`, `lead.stage_changed`, `lead.closed`. The test button sends `sx.test.v1`, with `event_type` `test`.

```json
{
  "closed_by": {
    "name": "TEST Owner WL-SYNTH",
    "ref": "per_42a09f0e8f1f423d9631561fcd8a927f"
  },
  "event_id": "8148ae9b-27f5-4d70-a637-948d39f09115",
  "event_type": "lead.closed",
  "lead": {
    "created_at": "2026-11-06T10:40:48Z",
    "ref": "lead_855c41ceaab7479ca905567085954eef",
    "source": "manual",
    "source_label": null,
    "test_data": false,
    "url": "https://salesxray-staging.authorityclosers.com/leads#lead=855c41ce-aab7-479c-a905-567085954eef"
  },
  "occurred_at": "2026-11-06T10:47:09Z",
  "reason": null,
  "result": "won",
  "schema": "sx.lead_event.v1",
  "tenant_ref": "ten_2647496292fe4424921c8de45d22e2e8"
}
```

Hand-over contract and its open decisions: `docs/contracts/partner-lead-handover-v1.md`. A fictional hand-over body:

```json
{
  "closing": {
    "closedAt": "2026-11-06T10:47:09Z",
    "salesperson": {
      "email": "s172.owner@wl-synth.example.test",
      "name": "TEST Owner WL-SYNTH"
    }
  },
  "customer": {
    "name": "TEST Lead B WL-SYNTH",
    "phone": "+911100000174"
  },
  "history": {
    "leadCreatedAt": "2026-11-06T10:40:48Z",
    "stages": [
      {
        "at": "2026-11-06T10:40:48Z",
        "stage": "New"
      },
      {
        "at": "2026-11-06T10:47:09Z",
        "stage": "Won"
      }
    ]
  },
  "links": [
    {
      "at": "2026-11-06T10:42:16Z",
      "kind": "analysis",
      "url": "https://salesxray-staging.authorityclosers.com/analysis/calls/5cea290d-e78f-438a-b307-9534b97a3f6b"
    }
  ],
  "source": {
    "accountId": "26474962-92fe-4424-921c-8de45d22e2e8",
    "leadId": "855c41ce-aab7-479c-a905-567085954eef",
    "leadUrl": "https://salesxray-staging.authorityclosers.com/leads#lead=855c41ce-aab7-479c-a905-567085954eef",
    "system": "sales_xray"
  }
}
```

## 5. Known limits, as seen on the fictional calls

- `lead` is null for a call not uploaded on a lead, so a receiver that matches by phone has nothing to match.
- `speaker` reads `unknown` until a speaker map exists for the call.
- A number word in a warranty can read null (`years`) with the words kept in `stated_as`.
- Facts were checked on one fictional English call only. Hindi and Marathi calls were not run.
