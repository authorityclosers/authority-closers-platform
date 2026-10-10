// Fictional API answers for the Sales Xray page matrix (AUT-1663).
// Every name, email and number here is invented; nothing comes from a real
// account. A read the stub does not know answers 404, like a server that does
// not have that route yet: pages must show an honest state, never crash.

export const ROLES = ["guest", "member", "admin", "owner", "personal"];

const TENANT = "22222222-2222-4222-8222-222222222222";
const PERSONAL = "33333333-3333-4333-8333-333333333333";
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const CALL_ID = uuid(500);
export const PROSPECT_ID = uuid(900);

const PEOPLE = [
  [1, "Asha Menon", "asha@brightline.example.in", "owner"],
  [2, "Rahul Verma", "rahul@brightline.example.in", "admin"],
  [3, "Neha Kulkarni", "neha@brightline.example.in", "member"],
  [4, "Vikram Shah", "vikram@brightline.example.in", "member"],
  [5, "Quinn Fixture", "qa-quinn@example.test", "member"],
];
// The viewer for each signed-in role.
const VIEWER = { owner: 1, admin: 2, member: 3, personal: 1 };

// [owner, days ago, seconds, state, name]
const CALLS = [
  [1, 0, 1520, "completed", "Discovery · Amit, Pixel Digital"],
  [2, 0, 940, "processing", null],
  [3, 1, 2210, "completed", "Follow-up · Kavita, Urban Nest"],
  [1, 2, 1835, "completed", "समीर जोशी · Pune follow-up"],
  [4, 3, 610, "failed", null],
  [3, 6, 1980, "completed", null],
  [1, 9, 2405, "completed", "Closing · Meera, Bloom Studio"],
];

const IST = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** One role's answers at a fixed time, keyed by path (and path?query). */
export function fixtureFor(role, now = Date.now()) {
  if (role === "guest") return {};
  const ago = (days, hour) => {
    const date = new Date(now - days * 86_400_000);
    date.setUTCHours(hour, 15, 0, 0);
    return date.toISOString();
  };
  const viewer = uuid(VIEWER[role]);
  const inOrg = role !== "personal";
  const team = role === "owner" || role === "admin";
  const selected = inOrg ? TENANT : PERSONAL;
  const name = (n) => PEOPLE.find(([id]) => id === n)[1];
  const calls = CALLS.map(([who, days, seconds, state, label], index) => ({
    id: uuid(500 + index),
    who,
    created_at: ago(days, 4 + index),
    seconds,
    state,
    label,
    has_report: state === "completed",
  })).filter((call) => team || call.who === VIEWER[role]);

  const submissions = calls.map((call) => ({
    submission_id: call.id,
    created_at: call.created_at,
    duration_seconds: call.seconds,
    state: call.state,
    has_report: call.has_report,
    display_name: call.label,
    display_name_revision: call.label ? 1 : 0,
    ...(team
      ? { owner_person_id: uuid(call.who), owner_name: name(call.who) }
      : {}),
  }));

  const days = Array.from({ length: 30 }, (_, index) => ({
    date: IST.format(new Date(now - (29 - index) * 86_400_000)),
    analysed: 0,
    analysed_seconds: 0,
  }));
  const byDate = new Map(days.map((day) => [day.date, day]));
  for (const call of calls.filter((item) => item.who === VIEWER[role])) {
    const day = byDate.get(IST.format(new Date(call.created_at)));
    if (!day || !call.has_report) continue;
    day.analysed += 1;
    day.analysed_seconds += call.seconds;
  }
  const analysed = days.reduce((sum, day) => sum + day.analysed, 0);

  const table = {
    "/v1/me/workspaces": {
      person_id: viewer,
      session_id: uuid(800 + VIEWER[role]),
      selected_tenant_id: selected,
      workspaces: [
        { tenant_id: PERSONAL, name: "Personal" },
        { tenant_id: TENANT, name: "Brightline Coaching" },
      ],
    },
    "/v1/me/sales-xray-workspaces": {
      selected_tenant_id: selected,
      workspaces: [
        {
          tenant_id: PERSONAL,
          kind: "personal",
          name: "Personal",
          role: null,
          sales_xray_enabled: true,
        },
        {
          tenant_id: TENANT,
          kind: "organisation",
          name: "Brightline Coaching",
          role: role === "personal" ? "owner" : role,
          sales_xray_enabled: true,
        },
      ],
    },
    "/v1/conversation/acquisition/session": {
      allowance: {
        allowance_seconds: 36_000,
        committed_seconds: 7_260,
        available_seconds: 28_740,
        unlimited: false,
      },
    },
    "/v1/conversation/acquisition/submissions": {
      submissions,
      next_cursor: null,
    },
    "/v1/conversation/acquisition/submissions/summary": {
      total: calls.length,
      processing: calls.filter((call) => call.state === "processing").length,
      completed: calls.filter((call) => call.has_report).length,
      needs_attention: calls.filter((call) => call.state === "failed").length,
    },
    "/v1/conversation/acquisition/activity": {
      timezone: "Asia/Kolkata",
      days,
      analysed_last_30_days: analysed,
      analysed_previous_30_days: 2,
    },
  };
  if (!inOrg) return table;

  const members = PEOPLE.map(([n, person, email, memberRole]) => ({
    person_id: uuid(n),
    invite_id: null,
    name: person,
    email,
    role: memberRole,
    status: "active",
    joined_at: ago(40 + n, 6),
    last_active_at: ago(n % 3, 6),
    minutes_used_30d: 0,
    calls_30d: 0,
  }));
  const counts = (rows) => ({
    calls: rows.length,
    recorded_minutes:
      Math.round(rows.reduce((sum, row) => sum + row.seconds, 0) / 6) / 10,
    reports_ready: rows.filter((row) => row.has_report).length,
  });
  const groups = (key) => {
    const out = new Map();
    for (const call of calls)
      out.set(key(call), [...(out.get(key(call)) ?? []), call]);
    return [...out];
  };
  Object.assign(table, {
    "/v1/organisation": {
      tenant_id: TENANT,
      name: "Brightline Coaching",
      role,
      verified_domains: ["brightline.example.in"],
      auto_join: false,
      member_count: members.length,
    },
    "/v1/organisation/members": { members },
    "/v1/organisation/activity?days=30": {
      members: [],
      calls: calls.map((call) => ({
        id: call.id,
        owner_person_id: uuid(call.who),
        owner_name: name(call.who),
        label: call.label,
        created_at: call.created_at,
        duration_seconds: call.seconds,
        state: call.state,
        has_report: call.has_report,
      })),
      per_day: groups((call) => call.created_at.slice(0, 10))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, rows]) => ({ date, ...counts(rows) })),
      per_rep: groups((call) => call.who).map(([who, rows]) => ({
        person_id: uuid(who),
        name: name(who),
        ...counts(rows),
      })),
    },
    "/v1/organisation/settings": {
      tenant_id: TENANT,
      name: "Brightline Coaching",
      legal_name: "Brightline Coaching Private Limited",
      gstin: "27AAACB1234F1Z5",
      address: "4th floor, 12 Example Road, Baner, Pune 411045",
      industry: "Sales coaching",
      team_size: "11-50",
      website: "https://brightline.example.in",
      city: "Pune",
      logo_url: null,
    },
  });
  for (const call of calls.filter((item) => item.has_report))
    table[`/v1/conversation/acquisition/submissions/${call.id}/report`] = {
      report: {
        content: {
          dimensions: [
            {
              dimension_id: "discovery",
              label: "Discovery",
              status: "partial",
            },
            {
              dimension_id: "next_step",
              label: "Next step",
              status: "observed",
            },
          ],
          overview: {
            outcome: { kind: "follow_up" },
            final_assessment: { fix_first: "Ask what the budget is." },
          },
        },
      },
    };
  return table;
}

/** The stub's answer to one browser request. */
export function answer(table, role, method, pathname, search) {
  if (role === "guest")
    return { status: 401, body: { detail: "Sign in to continue." } };
  if (method !== "GET" && method !== "HEAD")
    return { status: 409, body: { detail: "The page matrix does not write." } };
  const body = table[`${pathname}${search}`] ?? table[pathname];
  if (pathname === "/v1/organisation" && role === "personal")
    return { status: 404, body: { detail: "No organisation selected." } };
  return body === undefined
    ? { status: 404, body: { detail: "Not Found" } }
    : { status: 200, body };
}
