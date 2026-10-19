# Lead events and customer hand-overs to a partner, v1 (Sales X-Ray, 19 Oct 2026)

Sales X-Ray can send an organisation's leads onward. Code: `ac_platform/partner_events/lead_events.py`, migration `20261019_0102`. Everything is configured per organisation and environment, as data. Nothing in the code names a customer.

There are two kinds of recipient. An organisation has at most one active of each: its signed webhook (`partner_webhook_endpoints`, unchanged from 0096) and one hand-over recipient.

| Kind | Transport | What it receives |
|---|---|---|
| `webhook` | Signed POST as for `analysis.completed` (`X-SX-Event-Id`, `X-SX-Event-Type`, `X-SX-Signature: t=,v1=` HMAC-SHA256 over `"<t>." + body`, rejected outside 300 s) | `lead.created`, `lead.stage_changed`, `lead.closed` (schema `sx.lead_event.v1`), next to `analysis.completed` |
| hand-over recipient (`partner_handover_recipients`) | The partner's service API: `POST https://<install>/api/v1/service/customers/handover`, `Authorization: Bearer <scoped key>`, `Idempotency-Key: <uuid>` | One `HandoverRequest` per win (partner spec 1.0.1 §4) |

## Off by default, and approved per recipient

- Nothing is sent until an AC admin registers a recipient for that organisation and environment, using the `partner_events` CLI with `register-endpoint` and `--kind`. The registration records:
  - the exact URL;
  - the name of the secret that holds the key (the value lives only in Infisical);
  - the events;
  - for a hand-over, the approved optional parts and form questions (`--lead-fields`);
  - a reason and the approver's reference.

  Every registration writes an audit event.
- **Changes:** changing the URL, the key or the approved fields registers a new recipient that supersedes the old one. Old recipients are never edited. Undelivered requests move to the new recipient with their frozen bytes.
- **Test leads:** never sent from production.
- **Real hand-overs:** they wait for the consent, retention, security and release checks and the owner's yes. Until then, testing uses fictional data only.

### Approved hand-over parts (`lead_fields`)

```json
{"send": ["email", "address", "attribution", "requirement", "salesperson", "consents", "history", "links"],
 "questions": {"address.line1": "<exact form question>", "address.line2": "…", "address.city": "…",
               "address.state": "…", "address.pin_code": "…", "attribution.campaign": "…",
               "requirement.system_type": "…", "requirement.capacity_kw": "…"},
 "consents": [{"question": "<exact form question>", "purpose": "contact", "channel": "whatsapp"}]}
```

- **`send`:** the optional parts this recipient may receive. Parts not listed are never built.
- **`questions`:** each maps one request field to one exact question on the lead form; case and surrounding spaces are ignored. A later repeat enquiry's answer replaces an earlier one. An answer is sent word for word, only cleaned of unsafe characters.
- **What we never infer:**
  - `capacityKw` only from a plain number, optionally followed by kW ("5", "5.5 kW").
  - A consent only from a clear yes or no. Its `recordedAt` is when the answer arrived.
  - An address only with `line1` and a valid six-digit pin code.

  We never guess, fill in or work out anything else.
- **Never sent:** notes, remarks, deal values, call summaries, recordings, transcripts and scores. Calls go only as `links` (`kind: "analysis"`, the call's Sales X-Ray page), newest first, at most 20. Private calls and deleted calls are left out.

## The hand-over

- **When:** a person records a lead as **Won** in Lead Desk. A finished analysis never sends one.
- **Body:** the partner's `HandoverRequest`, with `additionalProperties: false` at every level:
  - `source{system:"sales_xray", accountId:<Sales X-Ray organisation id>, leadId, leadUrl}`;
  - `customer{name, phone, email?, address?}`;
  - `attribution?`, `requirement?`;
  - `closing{closedAt, salesperson?}`, where `closedAt` is when the person recorded Won and the salesperson is the lead's owner by work email;
  - `consents?`;
  - `history?{leadCreatedAt, stages[{stage, at}]}`;
  - `links?`;
  - `correctionOf?`.
- **Checked before sending:** the phone must be E.164 and the name must be present. If either check fails, the hand-over is stored as rejected **by Sales X-Ray** with the field path and problem, and nothing is sent.
- **Each win is its own request,** with a new `Idempotency-Key` (the request's id) and the same `leadId`. Reopening a lead sends nothing. Winning it again sends a new hand-over, which the partner applies as `updated`. Sales X-Ray numbers a lead's wins internally (`handover_seq`) and never sends that number.
- **Answers:**

  | Partner answer | What Sales X-Ray does |
  |---|---|
  | `201`, `200` or `202` | Delivered. We keep `result` (`created`, `updated`, `in_review`) and the customer code, never the rest of the body. |
  | `422` (and `400`, `409`, `413`) | Rejected: no retry. The key, field paths and problems are kept, never the body. An alert goes to AC. |
  | `429`, `5xx`, timeouts, `401`/`403` | Retried with the same key and bytes: 10 s doubling to 1 h, 25 attempts in about 16 h, well inside the partner's 30-day key window. Then dead-lettered with an alert, and replayed by hand. |

  `401` and `403` are retried because an install admin may still be approving the organisation.
- **Correction:** after fixing the lead, an operator runs `correct-handover --event-id <rejected id>`. This rebuilds the request from the lead as it is now, gives it a new key, and sends `correctionOf: <rejected key>` while the partner still keeps that key (30 days). After that it sends a fresh hand-over without `correctionOf`. A hand-over rejected by Sales X-Ray itself was never seen by the partner, so its correction is a fresh hand-over.

## Lead events (webhook)

Every event carries:
- `schema`, `event_id`, `event_type` and `occurred_at`;
- `tenant_ref`;
- `lead{ref, url, created_at, source, source_label, test_data}`, where `url` is `https://<Sales X-Ray>/leads#lead=<id>`.

| Event | Sent when | Extra fields |
|---|---|---|
| `lead.created` | A lead is captured | `customer{name, phone_e164, email, city}`, `salesperson{ref, name, email}` |
| `lead.stage_changed` | Any stage change; also a repeat enquiry that reopens a closed lead (`to_stage: "new"`, `reason: "repeat_enquiry"`) | `from_stage`, `to_stage`, `reason` (a fixed code or null), `changed_by{ref, name}` |
| `lead.closed` | The stage becomes Won or Lost | `result`, `reason`, `closed_by{ref, name}` |

Stages are `new`, `not_connected`, `follow_up`, `interested`, `won`, `lost`. No free-text remark is ever sent.

## What Sales X-Ray keeps

Each request's body is kept for 90 days, or until its lead is gone, whichever comes first. After that, only these remain:
- ids and the type;
- the digest;
- the status, the partner's result and customer code;
- rejection paths and problems;
- delivery attempts (status codes and content-free error codes), which are append-only.

## Links and sign-in from the partner's app

- Lead links (`/leads#lead=<id>`) and call links (`/analysis/calls/<id>`) open only for a signed-in member of the lead's organisation.
- **Proposal: quiet Google sign-in, matching the partner's own design.** Not built yet.
  - A link from the partner's app opens Sales X-Ray. With no session, `/login` makes one silent Google attempt:
    - OIDC code flow with PKCE, `prompt=none`;
    - `hd` when the organisation allows one domain;
    - a 10-minute "already tried" cookie, so it can't loop.
  - On success the person lands on the link. On failure they see the normal sign-in page.
  - Sign-in never creates a person, and the link still checks membership.
