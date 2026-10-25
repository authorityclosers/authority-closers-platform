/**
 * The public API reference for /developers: each endpoint with what it needs,
 * a curl and a JavaScript example, and an answer (shortened where long). Kept
 * to what packages/python/ac_platform/integrations/api_http.py serves; generic
 * and fictional throughout.
 */

export const HOST = "https://salesxray.authorityclosers.com";
export const API = `${HOST}/v1/api`;

export type Param = {
  name: string;
  where: "path" | "query" | "body";
  type: string;
  text: string;
};
export type EndpointDoc = {
  id: string;
  method: "GET" | "POST";
  path: string;
  scope: string | null;
  summary: string;
  params: Param[];
  curl: string;
  js: string;
  answer: string;
  notes?: string;
};

const AUTH = '-H "Authorization: Bearer $SX_API_KEY"';
const HEADERS = "{ Authorization: `Bearer ${process.env.SX_API_KEY}` }";

export const SCOPES: [string, string][] = [
  ["calls:read", "Read calls and their status"],
  ["reports:read", "Read the facts found in calls"],
  ["leads:read", "Read leads"],
  ["leads:write", "Add leads"],
  ["leads:notes", "Add notes to leads"],
  ["leads:tasks", "Add tasks and reminders to leads"],
  ["webhooks:manage", "Manage the webhook (coming to the API)"],
];

export const ENDPOINTS: EndpointDoc[] = [
  {
    id: "api-me",
    method: "GET",
    path: "/me",
    scope: null,
    summary:
      "Who is calling: the organisation, or for an app a person connected, that person and their workspace; with the permissions and the environment.",
    params: [],
    curl: `curl ${API}/me \\\n  ${AUTH}`,
    js: `const response = await fetch("${API}/me", {
  headers: ${HEADERS},
});
const me = await response.json();
console.log(me.organisation.name, me.key.scopes);`,
    answer: `{
  "organisation": { "id": "5b1e0c9a-…", "name": "Your organisation" },
  "key": { "prefix": "sxk_live_Ab12", "scopes": ["calls:read", "leads:read"] },
  "environment": "production",
  "reach": "organisation"
}`,
    notes:
      'For an app a person connected, reach is "person", and person {id, name} and workspace {id, kind: personal | organisation, name, role} say who and where.',
  },
  {
    id: "api-calls",
    method: "GET",
    path: "/calls",
    scope: "calls:read",
    summary:
      "Calls, newest first, 50 a page, each with its title and a link to it in Sales X-Ray.",
    params: [
      {
        name: "before",
        where: "query",
        type: "call id",
        text: "The last id of the page you have, for the next page (next_before).",
      },
    ],
    curl: `curl "${API}/calls" \\\n  ${AUTH}`,
    js: `// Every call, a page at a time.
let before = null;
do {
  const url = new URL("${API}/calls");
  if (before) url.searchParams.set("before", before);
  const page = await (await fetch(url, { headers: ${HEADERS} })).json();
  for (const call of page.calls) console.log(call.id, call.has_report);
  before = page.next_before;
} while (before);`,
    answer: `{
  "calls": [
    {
      "id": "3f2b7d10-…",
      "title": "Discovery call",
      "created_at": "2026-10-20T09:12:00+00:00",
      "duration_seconds": 1520,
      "has_report": true,
      "open_url": "${HOST}/analysis/calls/3f2b7d10-…"
    }
  ],
  "next_before": "3f2b7d10-…"
}`,
    notes:
      "next_before is null on the last page. The list follows what the library shows: deleted and expired calls are not in it.",
  },
  {
    id: "api-call",
    method: "GET",
    path: "/calls/{id}",
    scope: "calls:read",
    summary:
      "One call; with reports:read on the key, also the facts found in it.",
    params: [
      {
        name: "id",
        where: "path",
        type: "call id",
        text: "An id from GET /calls.",
      },
    ],
    curl: `curl ${API}/calls/3f2b7d10-… \\\n  ${AUTH}`,
    js: `const call = await (
  await fetch(\`${API}/calls/\${callId}\`, { headers: ${HEADERS} })
).json();
console.log(call.title, call.open_url, call.facts?.length);`,
    answer: `{
  "id": "3f2b7d10-…",
  "title": "Discovery call",
  "created_at": "2026-10-20T09:12:00+00:00",
  "duration_seconds": 1520,
  "has_report": true,
  "open_url": "${HOST}/analysis/calls/3f2b7d10-…",
  "facts": [{ "type": "timeline", "label": "Timeline", "display": "Wants to start next month", "…": "…" }]
}`,
    notes:
      "facts is null when the key lacks reports:read. A call that isn't there, or isn't yours to read, is 404 call_missing.",
  },
  {
    id: "api-facts",
    method: "GET",
    path: "/calls/{id}/facts",
    scope: "reports:read",
    summary:
      "The facts found in one call (needs, timeline, decision makers, objections, next steps…), each with the words it came from.",
    params: [
      {
        name: "id",
        where: "path",
        type: "call id",
        text: "An id from GET /calls.",
      },
    ],
    curl: `curl ${API}/calls/3f2b7d10-…/facts \\\n  ${AUTH}`,
    js: `const facts = await (
  await fetch(\`${API}/calls/\${callId}/facts\`, { headers: ${HEADERS} })
).json();
for (const fact of facts.facts) console.log(fact.label, fact.display);`,
    answer: `{
  "schema": "prospect-facts/1",
  "subject": { "kind": "call", "id": "3f2b7d10-…" },
  "taxonomy_version": "call-taxonomy/2",
  "facts": [
    {
      "object_id": "9a41…",
      "type": "timeline",
      "label": "Timeline",
      "display": "Wants to start next month",
      "confidence": 0.86,
      "status": "confirmed",
      "evidence": [
        { "quote": "We'd like to begin next month.", "start_ms": 412000, "role": "prospect" }
      ],
      "call": { "submission_id": "3f2b7d10-…", "at": "2026-10-20T09:12:00+00:00" }
    }
  ]
}`,
    notes:
      "Shortened: each fact carries a few more fields (category, kind, value, basis). Sensitive parts of a call are never quoted.",
  },
  {
    id: "api-leads",
    method: "GET",
    path: "/leads",
    scope: "leads:read",
    summary: "The organisation's leads, newest change first.",
    params: [
      {
        name: "stage",
        where: "query",
        type: "open | new | not_connected | follow_up | interested | won | lost",
        text: "Only leads in this stage.",
      },
      {
        name: "limit",
        where: "query",
        type: "1–50",
        text: "How many (default 50).",
      },
      {
        name: "offset",
        where: "query",
        type: "number",
        text: "Where to start; next_offset gives the next page.",
      },
    ],
    curl: `curl "${API}/leads?stage=new&limit=20" \\\n  ${AUTH}`,
    js: `const url = new URL("${API}/leads");
url.searchParams.set("stage", "new");
const page = await (await fetch(url, { headers: ${HEADERS} })).json();
console.log(page.total, page.leads.map((lead) => lead.name));`,
    answer: `{
  "schema": "lead-desk/1",
  "leads": [
    {
      "lead_id": "c7d2…",
      "name": "Asha Rao",
      "city": "Pune",
      "interest": "Weekend batch",
      "phone_last4": "0000",
      "stage": "new",
      "stage_label": "New",
      "source_label": "Website form",
      "owner_name": "Neha",
      "created_at": "2026-10-20T08:01:00+00:00"
    }
  ],
  "total": 41,
  "next_offset": 20
}`,
    notes:
      "Shortened: each lead carries more fields (next action, attempts, last result). Phone numbers show their last four digits here; GET /leads/{id} has the lead in full.",
  },
  {
    id: "api-lead",
    method: "GET",
    path: "/leads/{id}",
    scope: "leads:read",
    summary: "One lead with its details and history.",
    params: [
      {
        name: "id",
        where: "path",
        type: "lead id",
        text: "A lead_id from GET /leads.",
      },
    ],
    curl: `curl ${API}/leads/c7d2… \\\n  ${AUTH}`,
    js: `const lead = await (
  await fetch(\`${API}/leads/\${leadId}\`, { headers: ${HEADERS} })
).json();`,
    answer: `{
  "schema": "lead-desk/1",
  "lead": { "lead_id": "c7d2…", "name": "Asha Rao", "stage": "new", "…": "…" },
  "phone": "+919800000000",
  "email": null,
  "fields": [{ "label": "Interest", "value": "Weekend batch" }],
  "source_fields": [{ "label": "Preferred time", "value": "Evenings" }],
  "events": [{ "…": "…" }]
}`,
    notes:
      "Shortened. The lead as the Leads screen shows it: its row, phone and email in full, its fields, what its source sent, and its history.",
  },
  {
    id: "api-add-lead",
    method: "POST",
    path: "/leads",
    scope: "leads:write",
    summary:
      "Add a lead. Send at least a name, phone or email. The same external_id again changes nothing, so retries are safe.",
    params: [
      {
        name: "name",
        where: "body",
        type: "string",
        text: "Up to 200 characters.",
      },
      {
        name: "phone",
        where: "body",
        type: "string",
        text: "With the country code, e.g. +91 98000 00000.",
      },
      { name: "email", where: "body", type: "string", text: "" },
      {
        name: "company, city, interest",
        where: "body",
        type: "string",
        text: "Optional.",
      },
      {
        name: "note",
        where: "body",
        type: "string",
        text: "Up to 2,000 characters.",
      },
      {
        name: "external_id",
        where: "body",
        type: "string",
        text: "Your own id for this lead (up to 120).",
      },
    ],
    curl: `curl ${API}/leads \\\n  ${AUTH} \\\n  -H "Content-Type: application/json" \\\n  -d '{"name": "Asha Rao", "phone": "+919800000000", "interest": "Weekend batch", "external_id": "crm-42"}'`,
    js: `const response = await fetch("${API}/leads", {
  method: "POST",
  headers: { ...${HEADERS}, "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Asha Rao",
    phone: "+919800000000",
    interest: "Weekend batch",
    external_id: "crm-42",
  }),
});
const { id, outcome } = await response.json(); // 201 created, or 200`,
    answer: `{ "id": "c7d2…", "outcome": "created" }`,
    notes:
      "outcome is created (201), or 200 with known (this external_id was sent before) or repeat (a lead with this phone exists; it is marked as asking again).",
  },
  {
    id: "api-add-note",
    method: "POST",
    path: "/leads/{lead_id}/notes",
    scope: "leads:notes",
    summary:
      "Add a note to a lead. The lead's history shows it came from your key, and it can be undone for 7 days. The same request_id again changes nothing.",
    params: [
      { name: "lead_id", where: "path", type: "string", text: "From /leads." },
      {
        name: "note",
        where: "body",
        type: "string",
        text: "1 to 1,000 characters.",
      },
      {
        name: "request_id",
        where: "body",
        type: "string",
        text: "8 to 80 characters, new for each change.",
      },
      {
        name: "preview",
        where: "body",
        type: "boolean",
        text: "true: see what would change, without changing it.",
      },
    ],
    curl: `curl ${API}/leads/c7d2.../notes \\\n  ${AUTH} \\\n  -H "Content-Type: application/json" \\\n  -d '{"note": "Wants a demo on Monday", "request_id": "crm-note-42"}'`,
    js: `const response = await fetch("${API}/leads/" + leadId + "/notes", {
  method: "POST",
  headers: { ...${HEADERS}, "Content-Type": "application/json" },
  body: JSON.stringify({ note: "Wants a demo on Monday", request_id: "crm-note-42" }),
});
const { change_id, undo_until } = await response.json(); // 201, or 200 for a retry`,
    answer: `{ "change_id": "9b1e…", "action": "note", "lead_id": "c7d2…", "via": "API key sxk_live_ab12", "status": "applied", "undo_until": "2026-11-01T10:00:00+00:00" }`,
    notes:
      "Only these fields are taken. Refusals: 403 writes_paused (an owner paused changes from apps), 403 action_off, 429 cap_reached (200 a day per key, 20 per lead), 409 request_reused.",
  },
  {
    id: "api-add-task",
    method: "POST",
    path: "/leads/{lead_id}/tasks",
    scope: "leads:tasks",
    summary:
      "Add a task or reminder to a lead, for the lead's owner. It can be undone for 7 days while nobody has changed it.",
    params: [
      { name: "lead_id", where: "path", type: "string", text: "From /leads." },
      {
        name: "kind",
        where: "body",
        type: "string",
        text: "call_back, whatsapp, email, send_file, meeting or other.",
      },
      {
        name: "due",
        where: "body",
        type: "string",
        text: "Date and time with its time zone.",
      },
      {
        name: "title, note, ends_at, remind_before_minutes",
        where: "body",
        type: "",
        text: "Optional.",
      },
      {
        name: "request_id",
        where: "body",
        type: "string",
        text: "8 to 80 characters, new for each change.",
      },
    ],
    curl: `curl ${API}/leads/c7d2.../tasks \\\n  ${AUTH} \\\n  -H "Content-Type: application/json" \\\n  -d '{"kind": "call_back", "due": "2026-10-27T10:00:00+05:30", "request_id": "crm-task-42"}'`,
    js: `await fetch("${API}/leads/" + leadId + "/tasks", {
  method: "POST",
  headers: { ...${HEADERS}, "Content-Type": "application/json" },
  body: JSON.stringify({
    kind: "call_back",
    due: "2026-10-27T10:00:00+05:30",
    request_id: "crm-task-42",
  }),
});`,
    answer: `{ "change_id": "4a7c…", "action": "task", "task_id": "e21f…", "status": "applied" }`,
  },
  {
    id: "api-changes",
    method: "GET",
    path: "/changes",
    scope: "leads:notes or leads:tasks",
    summary:
      "The notes and tasks your key added in the last 30 days, newest first, and whether each can still be undone.",
    params: [
      {
        name: "lead_id",
        where: "query",
        type: "string",
        text: "Only this lead's.",
      },
    ],
    curl: `curl ${API}/changes \\\n  ${AUTH}`,
    js: `const { changes } = await (
  await fetch("${API}/changes", { headers: ${HEADERS} })
).json();`,
    answer: `{ "changes": [{ "change_id": "9b1e…", "action": "note", "lead_name": "Asha Rao", "status": "applied", "can_undo": true }] }`,
  },
  {
    id: "api-undo",
    method: "POST",
    path: "/changes/{change_id}/undo",
    scope: "leads:notes or leads:tasks",
    summary:
      "Undo one change your key made, within 7 days: a note stops showing, an open task is cancelled. Both stay in the lead's history.",
    params: [
      {
        name: "change_id",
        where: "path",
        type: "string",
        text: "From the change or /changes.",
      },
    ],
    curl: `curl -X POST ${API}/changes/9b1e.../undo \\\n  ${AUTH}`,
    js: `await fetch("${API}/changes/" + changeId + "/undo", {
  method: "POST",
  headers: ${HEADERS},
});`,
    answer: `{ "change_id": "9b1e…", "status": "undone", "undo_change_id": "77c0…" }`,
    notes:
      "409 changed_since: someone changed the task in Sales X-Ray since, and their change stands.",
  },
];

export const EVENTS: [string, string][] = [
  [
    "analysis.completed",
    "A call's analysis is ready (sx.analysis_completed.v1)",
  ],
  ["lead.created", "A lead is added (sx.lead_event.v1)"],
  [
    "lead.stage_changed",
    "A lead moves stage, including a reopen (sx.lead_event.v1)",
  ],
  ["lead.closed", "A lead is won or lost (sx.lead_event.v1)"],
];

export const EVENT_SAMPLE = `POST /your/webhook HTTP/1.1
Content-Type: application/json
X-SX-Event-Id: 1f6e2c4a-…
X-SX-Event-Type: lead.created
X-SX-Signature: t=1760950800,v1=5d41402abc4b2a76b9719d911017c592…

{
  "schema": "sx.lead_event.v1",
  "event_id": "1f6e2c4a-…",
  "event_type": "lead.created",
  "occurred_at": "2026-10-20T08:01:00Z",
  "tenant_ref": "ten_…",
  "lead": {
    "ref": "lead_…",
    "url": "${HOST}/leads#lead=c7d2…",
    "source": "webhook",
    "source_label": "Website form",
    "test_data": false
  },
  "customer": { "name": "Asha Rao", "phone_e164": "+919800000000", "email": null, "city": "Pune" },
  "salesperson": { "ref": "per_…", "name": "Neha", "email": "neha@example.com" }
}`;

export const NODE_VERIFY = `import crypto from "node:crypto";

// rawBody: the exact bytes received; secret: your whsec_... signing secret
export function verify(rawBody, header, secret, now = Date.now() / 1000) {
  const items = header.split(",").map((part) => part.split("="));
  const t = Number(items.find(([key]) => key === "t")?.[1]);
  if (!t || Math.abs(now - t) > 300) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(\`\${t}.\`)
    .update(rawBody)
    .digest();
  return items
    .filter(([key]) => key === "v1")
    .some(([, value]) => {
      const given = Buffer.from(value, "hex");
      return given.length === expected.length && crypto.timingSafeEqual(given, expected);
    });
}`;

export const PYTHON_VERIFY = `import hashlib, hmac, time

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    items = [part.split("=", 1) for part in header.split(",")]
    t = next((int(v) for k, v in items if k == "t"), 0)
    if not t or abs(time.time() - t) > 300:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(k == "v1" and hmac.compare_digest(v, expected) for k, v in items)`;

export const CONNECT_URL = `${HOST}/connect?response_type=code
  &client_id=sxc_...
  &redirect_uri=https://your-app.example.com/sales-xray/callback
  &scope=calls:read%20leads:read
  &state=<random>
  &code_challenge=<BASE64URL(SHA256(verifier))>
  &code_challenge_method=S256`;

export const TOKEN = `curl ${HOST}/v1/oauth/token \\
  -d grant_type=authorization_code \\
  -d code=sxo_... \\
  -d redirect_uri=https://your-app.example.com/sales-xray/callback \\
  -d code_verifier=<verifier> \\
  -u sxc_...:sxcs_...        # client secret; public apps send client_id and no secret`;

export const MCP_URL = `${HOST}/v1/mcp`;

export const MCP_TOOLS: [string, string, string][] = [
  ["whoami", "any", "Who this connection reads as, and its scopes"],
  ["list_calls", "calls:read", "Calls, newest first"],
  ["get_call", "calls:read", "One call, with its facts when allowed"],
  ["call_facts", "reports:read", "The facts found in one call"],
  ["list_leads", "leads:read", "Leads, by stage"],
  ["get_lead", "leads:read", "One lead with its history"],
  ["add_lead", "leads:write", "Add a lead"],
  ["add_note", "leads:notes", "Add a note to a lead (undo for 7 days)"],
  ["add_task", "leads:tasks", "Add a task or reminder to a lead"],
  ["list_my_changes", "leads:notes or leads:tasks", "What this app added"],
  ["undo_change", "leads:notes or leads:tasks", "Undo one of its changes"],
];

/** The remote MCP server in each assistant: add the address, then sign in. */
export const REMOTE_SETUPS: {
  key: string;
  label: string;
  where: string;
  code: string;
}[] = [
  {
    key: "claude-desktop",
    label: "Claude Desktop",
    where:
      "Settings → Connectors → Add custom connector. Paste the address, then sign in to Sales X-Ray.",
    code: MCP_URL,
  },
  {
    key: "claude-code",
    label: "Claude Code",
    where: "Run once in a terminal, then /mcp to sign in.",
    code: `claude mcp add --transport http sales-xray ${MCP_URL}`,
  },
  {
    key: "cursor",
    label: "Cursor",
    where: "~/.cursor/mcp.json. Cursor asks you to sign in.",
    code: `{
  "mcpServers": {
    "sales-xray": { "url": "${MCP_URL}" }
  }
}`,
  },
  {
    key: "vscode",
    label: "VS Code",
    where: ".vscode/mcp.json in your project. VS Code asks you to sign in.",
    code: `{
  "servers": {
    "sales-xray": { "type": "http", "url": "${MCP_URL}" }
  }
}`,
  },
  {
    key: "key",
    label: "With an API key",
    where:
      "For a server of your own: no sign-in; it reads as the key's organisation.",
    code: `{
  "mcpServers": {
    "sales-xray": {
      "url": "${MCP_URL}",
      "headers": { "Authorization": "Bearer sxk_live_..." }
    }
  }
}`,
  },
];

export const REGISTER = `curl ${HOST}/v1/oauth/register \\
  -H "Content-Type: application/json" \\
  -d '{"client_name": "Your App",
       "redirect_uris": ["https://your-app.example.com/sales-xray/callback"],
       "grant_types": ["authorization_code", "refresh_token"],
       "token_endpoint_auth_method": "client_secret_basic"}'
# 201: {"client_id": "sxc_...", "client_secret": "sxcs_...", ...}
# Apps with no server of their own send "token_endpoint_auth_method": "none".`;

export const MCP_SETUPS: {
  key: string;
  label: string;
  where: string;
  code: string;
}[] = [
  {
    key: "claude-desktop",
    label: "Claude Desktop",
    where: "Settings → Developer → Edit config, then restart Claude.",
    code: `{
  "mcpServers": {
    "sales-xray": {
      "command": "python3",
      "args": ["/path/to/sx.py", "mcp"],
      "env": { "SX_API_KEY": "paste-your-key-here" }
    }
  }
}`,
  },
  {
    key: "claude-code",
    label: "Claude Code",
    where: "Run once in a terminal.",
    code: `claude mcp add sales-xray \\
  --env SX_API_KEY=paste-your-key-here \\
  -- python3 /path/to/sx.py mcp`,
  },
  {
    key: "cursor",
    label: "Cursor",
    where: "~/.cursor/mcp.json, or .cursor/mcp.json in a project.",
    code: `{
  "mcpServers": {
    "sales-xray": {
      "command": "python3",
      "args": ["/path/to/sx.py", "mcp"],
      "env": { "SX_API_KEY": "paste-your-key-here" }
    }
  }
}`,
  },
  {
    key: "vscode",
    label: "VS Code",
    where: ".vscode/mcp.json in your project.",
    code: `{
  "servers": {
    "sales-xray": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/sx.py", "mcp"],
      "env": { "SX_API_KEY": "paste-your-key-here" }
    }
  }
}`,
  },
];

export const ERRORS: [number, string, string][] = [
  [401, "key_missing", "No key was sent. Send Authorization: Bearer sxk_…"],
  [401, "key_invalid", "The key is wrong, expired or revoked."],
  [403, "scope_missing", "The key lacks the permission this request needs."],
  [403, "organisation_missing", "The key's organisation is no longer active."],
  [
    403,
    "access_ended",
    "The person who connected this app no longer has access to that workspace.",
  ],
  [
    403,
    "organisation_only",
    "Leads are kept in organisations, not in Personal.",
  ],
  [404, "call_missing", "That call isn't there, or isn't yours to read."],
  [404, "cursor_missing", "The before id is not in this list."],
  [404, "not_here", "The API is served on the Sales X-Ray address only."],
  [422, "lead_empty", "A new lead needs at least a name, phone or email."],
  [422, "stage_unknown", "stage is not one of the stages listed above."],
  [
    429,
    "rate_limited",
    "More than 120 requests in a minute. Wait Retry-After seconds.",
  ],
];
