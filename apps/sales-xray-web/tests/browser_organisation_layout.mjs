// Fictional API render fixture only; this does not verify a saved call or login.
// Run against the ui lane dev server through the shared heavy slot:
//   AC_ORG_LAYOUT_URL=http://127.0.0.1:3026 node tests/browser_organisation_layout.mjs
// Writes screenshots and layout.json to AC_ORG_LAYOUT_OUT (or the run scratch dir).
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const origin = process.env.AC_ORG_LAYOUT_URL ?? "http://127.0.0.1:3026";
const output =
  process.env.AC_ORG_LAYOUT_OUT ??
  process.env.PAPERCLIP_RUN_SCRATCH_DIR ??
  "organisation-layout";
const only = process.env.AC_ORG_LAYOUT_ONLY?.split(",");
const tenant = "22222222-2222-4222-8222-222222222222";
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const now = Date.now();
const ago = (days, hour = 10) => {
  const date = new Date(now - days * 86_400_000);
  date.setUTCHours(hour, 15, 0, 0);
  return date.toISOString();
};

const person = (n, name, email, role, extra = {}) => ({
  person_id: uuid(n),
  invite_id: null,
  name,
  email,
  role,
  status: "active",
  joined_at: ago(60 - n),
  last_active_at: ago(n % 4),
  minutes_used_30d: 0,
  calls_30d: 0,
  ...extra,
});

const rich = {
  name: "Brightline Coaching",
  members: [
    person(1, "Asha Menon", "asha@brightline.example.in", "owner"),
    person(2, "Rahul Verma", "rahul@brightline.example.in", "admin"),
    person(3, "Neha Kulkarni", "neha@brightline.example.in", "member"),
    person(4, "Vikram Shah", "vikram@brightline.example.in", "member"),
    person(5, "Priya Nair", "priya@brightline.example.in", "member"),
    person(6, "Brightline Coaching", "team@brightline.example.in", "member"),
    person(
      7,
      "Brightline Coaching",
      "brightline.desk@mail.example.in",
      "member",
    ),
    person(8, "Quinn Fixture", "qa-quinn@example.test", "member"),
    {
      ...person(9, null, "arjun@brightline.example.in", "member"),
      person_id: null,
      invite_id: uuid(99),
      status: "invited",
      joined_at: null,
      last_active_at: null,
    },
  ],
  calls: [
    [1, 0, 1520, "report_ready", "Discovery · Amit, Pixel Digital"],
    [2, 0, 940, "processing", null],
    [3, 1, 2210, "report_ready", "Follow-up · Kavita, Urban Nest"],
    [1, 2, 1835, "report_ready", "Pricing call · Rohan Mehta"],
    [4, 3, 610, "failed", null],
    [2, 4, 1310, "report_ready", "Discovery · Sameer, Vista Labs"],
    [3, 6, 1980, "report_ready", null],
    [1, 8, 2405, "report_ready", "Closing · Meera, Bloom Studio"],
    [3, 11, 1150, "report_ready", "Discovery · Farhan, Northpeak"],
    [2, 13, 1625, "report_ready", null],
    [1, 17, 845, "report_ready", "Check-in · Dev, Arc Fitness"],
    [3, 20, 2030, "report_ready", "Discovery · Ishita, Kite Media"],
    [4, 24, 1460, "report_ready", null],
    [1, 27, 1770, "report_ready", "Demo · Tanvi, Ledgerly"],
  ],
};

// The owner's dev organisation today: one permitted call, mostly idle people.
const sparse = {
  name: "Authority Closers",
  members: [
    person(1, "Authority Closers", "owner@ac.example.in", "owner"),
    person(
      2,
      "Authority Closers",
      "authorityclosers@mail.example.in",
      "member",
    ),
    person(3, "Suyog Patil", "suyog@ac.example.in", "admin"),
    person(4, "Dipak Rao", "dipak@ac.example.in", "member"),
    person(5, "Mitali Joshi", "mitali@ac.example.in", "member"),
    person(6, "Quinn Fixture", "qa-quinn@example.test", "member"),
    person(7, "AC Alpha Learner", "alpha-learner@example.test", "member"),
  ],
  calls: [[1, 6, 252, "report_ready", null]],
};

function fixture(org) {
  const names = new Map(
    org.members.map((member) => [member.person_id, member.name]),
  );
  const calls = org.calls.map(([who, days, seconds, state, label], index) => ({
    id: uuid(500 + index),
    owner_person_id: uuid(who),
    owner_name: names.get(uuid(who)),
    label,
    created_at: ago(days, 9 + (index % 7)),
    duration_seconds: seconds,
    state,
    has_report: state === "report_ready",
  }));
  const bucket = (key) => {
    const out = new Map();
    for (const call of calls) {
      const id = key(call);
      const row = out.get(id) ?? { calls: 0, seconds: 0, reports: 0 };
      row.calls += 1;
      row.seconds += call.duration_seconds;
      row.reports += call.has_report ? 1 : 0;
      out.set(id, row);
    }
    return out;
  };
  const counts = ({ calls: c, seconds, reports }) => ({
    calls: c,
    recorded_minutes: Math.round(seconds / 6) / 10,
    reports_ready: reports,
  });
  return {
    "/v1/me/workspaces": {
      person_id: uuid(1),
      session_id: uuid(1),
      selected_tenant_id: tenant,
      workspaces: [{ tenant_id: tenant, name: org.name }],
    },
    "/v1/me/sales-xray-workspaces": {
      selected_tenant_id: tenant,
      workspaces: [
        {
          tenant_id: "personal",
          kind: "personal",
          name: "Personal",
          role: null,
          sales_xray_enabled: true,
        },
        {
          tenant_id: tenant,
          kind: "organisation",
          name: org.name,
          role: "owner",
          sales_xray_enabled: true,
        },
      ],
    },
    "/v1/conversation/acquisition/session": {
      allowance: {
        allowance_seconds: 36_000,
        committed_seconds: 1_200,
        available_seconds: 34_800,
        unlimited: true,
      },
    },
    "/v1/organisation": {
      tenant_id: tenant,
      name: org.name,
      role: "owner",
      verified_domains: ["brightline.example.in"],
      auto_join: true,
      member_count: org.members.filter((item) => item.status === "active")
        .length,
    },
    "/v1/organisation/members": { members: org.members },
    "/v1/organisation/activity": {
      members: [],
      calls,
      per_day: [...bucket((call) => call.created_at.slice(0, 10))]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, row]) => ({ date, ...counts(row) })),
      per_rep: [...bucket((call) => call.owner_person_id)].map(([id, row]) => ({
        person_id: id,
        name: names.get(id),
        ...counts(row),
      })),
    },
    "/v1/organisation/settings": {
      tenant_id: tenant,
      name: org.name,
      legal_name: `${org.name} Private Limited`,
      gstin: "27AAACB1234F1Z5",
      address: "4th floor, 12 Example Road, Baner, Pune 411045",
      industry: "Sales coaching",
      team_size: "11-50",
      website: "https://brightline.example.in",
      city: "Pune",
      logo_url: null,
    },
  };
}

const shots = [
  ["overview", rich, ""],
  ["overview-sparse", sparse, ""],
  ["members", rich, "?tab=members"],
  ["company", rich, "?tab=company"],
];
const report = [];
const browser = await chromium.launch({ headless: true });
await mkdir(output, { recursive: true });
try {
  for (const scheme of ["light", "dark"]) {
    for (const width of [1440, 390]) {
      for (const [name, org, query] of shots) {
        const key = `org-${name}-${width}-${scheme}`;
        if (only && !only.some((item) => key.includes(item))) continue;
        const routes = fixture(org);
        const context = await browser.newContext({
          viewport: { width, height: width === 390 ? 844 : 960 },
          deviceScaleFactor: width === 390 ? 2 : 1,
          colorScheme: scheme,
        });
        const page = await context.newPage();
        const writes = [];
        await page.route("**/v1/**", async (route) => {
          const request = route.request();
          if (request.method() !== "GET") writes.push(request.method());
          const body = routes[new URL(request.url()).pathname];
          await route.fulfill({ status: body ? 200 : 404, json: body ?? {} });
        });
        await page.goto(`${origin}/organisation${query}`, {
          waitUntil: "networkidle",
          timeout: 120_000,
        });
        await page.locator("[data-organisation-view] h1").first().waitFor();
        const closeGuide = page.getByRole("button", { name: "Close guide" });
        if (await closeGuide.count()) await closeGuide.first().click();
        await page.waitForTimeout(400);
        const layout = await page.evaluate(() => {
          const view = document.querySelector("[data-organisation-view]");
          const limit = document.documentElement.clientWidth;
          const overflow = [...view.querySelectorAll("*")]
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return rect.width > 0 && rect.right > limit + 1;
            })
            .map((node) => node.className || node.tagName)
            .slice(0, 5);
          return {
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: limit,
            height: document.documentElement.scrollHeight,
            overflow,
          };
        });
        if (width < 720) {
          // What the phone shows first, then the whole page without the fixed
          // bottom navigation repeated over the middle of the stitched image.
          await page.screenshot({ path: join(output, `${key}-top.png`) });
          await page.addStyleTag({
            content: "[class*='bottomNav']{display:none!important}",
          });
        }
        await page.screenshot({
          path: join(output, `${key}.png`),
          fullPage: true,
        });
        report.push({ key, writes, ...layout });
        assert.deepEqual(writes, [], `${key} made writes`);
        assert.ok(
          layout.scrollWidth <= layout.clientWidth,
          `${key} scrolls sideways`,
        );
        assert.deepEqual(layout.overflow, [], `${key} overflows the viewport`);
        await context.close();
      }
    }
  }
} finally {
  await writeFile(join(output, "layout.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
console.log(JSON.stringify(report.map(({ key, height }) => ({ key, height }))));
