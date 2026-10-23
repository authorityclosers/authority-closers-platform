// Sales X-Ray speed on a mid-range phone profile (app speed, 23 Oct 2026),
// signed in with a fictional workspace: every /v1 answer is fictional and
// served by this script after a fixed delay (no login, no account, nothing
// reaches an API). Times a cold open of Calls, the tab switches to Leads and
// back, and opening a lead, and writes one JSON line per run.
//
// Profile: 393 x 810, Android UA, touch, CPU slowed 4x (as Lighthouse's
// mobile run), each API answer held LATENCY ms (a phone on 4G to the server).
//
// Modes:
//   after   the app as it is.
//   before  the app as it was before the speed work: no early reads on a tab
//           press (the session flag they need is never stored) and nothing
//           read ahead (lead details and Start calling's /next asked before
//           the tap fail, so the opening reads for itself).
//
// Where: ORIGIN is the app (default: the dev server, next dev on loopback). A
// production build in a container: ORIGIN=http://localhost:3399 (a loopback
// origin, which the app needs as a secure context) with UPSTREAM= the
// container's address; its files are fetched from there.
//
// Usage: node tests/browser_speed.mjs <out.jsonl> <mode> [runs]
// Run 0 warms the server and is recorded like the others.
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const [out, mode = "after", runsArg = "3"] = process.argv.slice(2);
const RUNS = Number(runsArg);
const ORIGIN = process.env.ORIGIN ?? "http://127.0.0.1:3026";
const UPSTREAM = process.env.UPSTREAM ?? "";
const LATENCY = Number(process.env.LATENCY ?? 300);
const CPU = Number(process.env.CPU ?? 4);
const ANDROID_UA =
  "Mozilla/5.0 (Linux; Android 13; Redmi Note 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";

const PERSON = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const CALL = "11111111-1111-4111-8111-111111111111";
const MINUTE = 60_000;

const LEADS = [
  ["asha fictional", "Pune", "2 BHK", "new", "New", "due"],
  ["ravi sample", "Mumbai", "Site visit", "follow_up", "Follow up", "due"],
  [
    "meera fictional",
    "Nashik",
    "Plot",
    "not_connected",
    "Couldn't reach",
    "retry",
  ],
  [
    "karan example",
    "Pune",
    "Office space",
    "interested",
    "Interested",
    "later",
  ],
  ["neha fictional", "Thane", "Villa", "new", "New", "new"],
  ["sample buyer", null, null, "follow_up", "Follow up", "later"],
];

function rows(now) {
  return LEADS.map(([name, city, interest, stage, label, why], index) => ({
    lead_id: `00000000-0000-4000-8000-0000000003${String(index).padStart(2, "0")}`,
    revision: 1,
    name,
    company: null,
    city,
    language: null,
    interest,
    phone_last4: "3210",
    stage,
    stage_label: label,
    source: "manual",
    source_label: "Added by hand",
    owner_person_id: PERSON,
    owner_name: "priya owner",
    why: why === "due" ? "Call back now" : why === "new" ? "New" : "Later",
    why_kind: why,
    next_action_at: new Date(now + (index - 2) * 30 * MINUTE).toISOString(),
    created_at: new Date(now - index * 90 * MINUTE).toISOString(),
    attempts: index % 3,
    calls: index % 4,
    last_result: null,
    last_result_label: null,
    test_data: false,
    overdue: index === 1,
    pipeline: "main",
  }));
}

function detail(row) {
  return {
    lead: row,
    phone: "+91 98765 43210",
    email: null,
    owner_reason: null,
    next_action_note: null,
    fields: [],
    source_fields: [],
    events: [],
    can_edit: true,
    can_assign: true,
    reps: [],
    call_mode: "phone",
    first_call_minutes: null,
    stage_suggestion: null,
    stage_choices: [],
  };
}

function answer(path) {
  const now = Date.now();
  const [bare, query = ""] = path.split("?");
  const all = rows(now);
  if (bare === "/v1/me/workspaces")
    return {
      person_id: PERSON,
      session_id: SESSION,
      selected_tenant_id: TENANT,
      workspaces: [{ tenant_id: TENANT, name: "Fictional speed fixture" }],
    };
  if (bare === "/v1/me/sales-xray-workspaces")
    return {
      selected_tenant_id: TENANT,
      workspaces: [
        {
          tenant_id: TENANT,
          name: "Fictional speed fixture",
          kind: "personal",
          role: "owner",
          sales_xray_enabled: true,
        },
      ],
    };
  if (bare === "/v1/lead-desk")
    return {
      me: {
        person_id: PERSON,
        name: "priya owner",
        role: "owner",
        can_manage: false,
        taking_leads: true,
        paused_until: null,
      },
      numbers: {
        calls: 14,
        connected: 6,
        talk_seconds: 2_460,
        follow_ups_done: 3,
        new_assigned: 4,
      },
      counts: {
        open: 6,
        new: 2,
        follow_up_due: 2,
        not_connected: 1,
        later_today: 2,
        unassigned: 0,
        overdue: 1,
        call_back: 0,
      },
      queue: all,
      call_mode: "phone",
      sandbox: false,
      generated_at: new Date(now).toISOString(),
      upcoming: [],
      templates: [],
      call_back: [],
    };
  if (bare === "/v1/me/consent")
    return {
      status: "current",
      current_version: "fictional-1",
      document: {
        version: "fictional-1",
        acknowledgement: "I agree to the fictional Terms.",
        terms_path: "/terms",
        privacy_path: "/privacy",
      },
    };
  if (bare === "/v1/lead-desk/journey")
    return {
      version: 2,
      industry: "real_estate",
      savedAt: null,
      savedBy: null,
      canEdit: true,
      kinds: {},
      meanings: {},
      stages: [
        ["Enquiry", "new"],
        ["Not reachable", "not_connected"],
        ["Call back", "follow_up"],
        ["Site visit booked", "interested"],
        ["Booked", "won"],
        ["Not interested", "lost"],
      ].map(([label, kind], index) => ({
        key: `step_${index}`,
        label,
        kind,
        kindWords: "",
        milestone: "",
        meaning: "",
        archived: false,
        origin: "",
        leads: 1,
      })),
    };
  if (bare === "/v1/lead-desk/badge")
    return {
      overdue: 1,
      to_call: 3,
      generated_at: new Date(now).toISOString(),
    };
  if (bare === "/v1/lead-desk/next") {
    const skip = new URLSearchParams(query).get("skip");
    return detail(skip === all[1].lead_id ? all[2] : all[1]);
  }
  const one = /^\/v1\/lead-desk\/leads\/([0-9a-f-]{36})$/.exec(bare);
  if (one) {
    const row = all.find((item) => item.lead_id === one[1]);
    return row ? detail(row) : null;
  }
  if (bare === "/v1/conversation/acquisition/submissions")
    return {
      submissions: [
        {
          submission_id: CALL,
          created_at: new Date(now - 90 * MINUTE).toISOString(),
          duration_seconds: 195,
          state: "completed",
          has_report: true,
          display_name: null,
          display_name_revision: 0,
        },
      ],
      next_cursor: null,
    };
  if (bare === `/v1/conversation/acquisition/submissions/${CALL}/report`)
    return { verdict: "Fictional discovery conversation for a speed check." };
  return null;
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const browser = await chromium.launch();

async function run(index) {
  const context = await browser.newContext({
    viewport: { width: 393, height: 810 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    userAgent: ANDROID_UA,
    reducedMotion: "reduce",
  });
  if (mode === "before")
    await context.addInitScript(() => {
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (key === "sx.early.conversation") return;
        return set.call(this, key, value);
      };
    });
  // Before: lead details and /next asked before the tap are not there.
  const tapped = { lead: false, calling: false };
  const asked = [];
  // UPSTREAM: the page stays on a loopback origin (a secure context, as the
  // app needs for crypto.randomUUID) and its files come from that server.
  if (UPSTREAM)
    await context.route(`${ORIGIN}/**`, async (route) => {
      const url = new URL(route.request().url());
      try {
        await route.fulfill({
          response: await route.fetch({
            url: `${UPSTREAM}${url.pathname}${url.search}`,
            maxRedirects: 0,
          }),
        });
      } catch {
        await route.abort();
      }
    });
  await context.route(`${ORIGIN}/v1/**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname + url.search;
    asked.push(path);
    if (mode === "before") {
      if (
        !tapped.lead &&
        /^\/v1\/lead-desk\/leads\/[0-9a-f-]{36}$/.test(url.pathname)
      )
        return route.abort();
      if (
        !tapped.calling &&
        url.pathname === "/v1/lead-desk/next" &&
        !url.search.includes("skip")
      )
        return route.abort();
    }
    await wait(LATENCY);
    const body = route.request().method() === "GET" ? answer(path) : null;
    if (!body) missing.add(`${route.request().method()} ${url.pathname}`);
    await route.fulfill({ status: body ? 200 : 404, json: body ?? {} });
  });
  const missing = new Set();
  const errors = [];
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(String(error).slice(0, 240)));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource")
    )
      errors.push(message.text().slice(0, 400));
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU });
  const result = {
    origin: ORIGIN,
    mode,
    run: index,
    latency: LATENCY,
    cpu: CPU,
  };
  const timed = async (name, act, ready) => {
    const start = Date.now();
    await act();
    try {
      await ready();
    } catch (error) {
      await page.screenshot({ path: `${out}.${mode}.${name}.png` });
      console.log(
        JSON.stringify({
          stuck: name,
          errors: errors.slice(0, 4),
          missing: [...missing],
        }),
      );
      throw error;
    }
    result[name] = Date.now() - start;
  };
  const visible = (selector) => () =>
    page
      .locator(selector)
      .first()
      .waitFor({ state: "visible", timeout: 60_000 });
  // A lead row, by its fictional name (older releases mark rows differently).
  const leadRow = () => page.getByText(/asha fictional/i).first();
  const leadsReady = () =>
    leadRow().waitFor({ state: "visible", timeout: 60_000 });
  const tab = (href) => () =>
    page.locator(`a[href="${href}"]:visible`).last().tap();

  // 1. A cold open of Calls (the app's first paint), then the tabs.
  await timed(
    "calls_cold_open",
    () =>
      page.goto(`${ORIGIN}/analysis/calls`, {
        waitUntil: "commit",
        timeout: 180_000,
      }),
    visible(".calls-library-row"),
  );
  result.calls_fcp = await page.evaluate(
    () =>
      performance.getEntriesByName("first-contentful-paint")[0]?.startTime ??
      null,
  );
  await wait(2_500); // the app settles; idle prefetch runs
  await timed("tab_to_leads_first", tab("/leads"), leadsReady);
  await wait(2_500); // read ahead lands (after mode)
  await timed(
    "tab_to_calls",
    tab("/analysis/calls"),
    visible(".calls-library-row"),
  );
  await wait(1_000);
  await timed("tab_back_to_leads", tab("/leads"), leadsReady);
  await wait(2_500);
  tapped.lead = true;
  await timed(
    "open_lead",
    () => leadRow().tap(),
    () =>
      page
        .getByText("98765 43210")
        .first()
        .waitFor({ state: "visible", timeout: 60_000 }),
  );
  result.asked = asked.length;
  appendFileSync(out, JSON.stringify(result) + "\n");
  console.log(JSON.stringify(result));
  await context.close();
}

for (let index = 0; index <= RUNS; index += 1) {
  try {
    // Run 0 warms the dev server's compiled pages; it is recorded as warm-up.
    await run(index);
  } catch (error) {
    console.log(
      JSON.stringify({ mode, run: index, error: String(error).slice(0, 300) }),
    );
  }
}
await browser.close();
