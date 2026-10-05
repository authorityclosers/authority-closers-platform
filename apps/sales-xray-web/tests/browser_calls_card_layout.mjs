// Fictional API render fixture only; this does not verify a saved call or login.
// Run against the existing lane preview: node tests/browser_calls_card_layout.mjs
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const origin = process.env.AC_CALLS_LAYOUT_URL ?? "http://127.0.0.1:3040";
const output = process.env.PAPERCLIP_RUN_SCRATCH_DIR;
const id = "11111111-1111-4111-8111-111111111111";
const tenant = "22222222-2222-4222-8222-222222222222";
const fixture = {
  "/v1/me/workspaces": {
    person_id: id,
    session_id: id,
    selected_tenant_id: tenant,
    workspaces: [{ tenant_id: tenant, name: "Fictional layout fixture" }],
  },
  "/v1/me/sales-xray-workspaces": {
    selected_tenant_id: tenant,
    workspaces: [
      {
        tenant_id: tenant,
        name: "Fictional layout fixture",
        kind: "personal",
        role: "owner",
        sales_xray_enabled: true,
      },
    ],
  },
  "/v1/conversation/acquisition/submissions": {
    submissions: [
      {
        submission_id: id,
        created_at: "2026-10-04T07:14:00Z",
        duration_seconds: 195,
        state: "completed",
        has_report: true,
        display_name: null,
        display_name_revision: 0,
      },
    ],
    next_cursor: null,
  },
  [`/v1/conversation/acquisition/submissions/${id}/report`]: {
    verdict:
      "Fictional discovery conversation with operational details for a layout check.",
  },
};
const receipts = [];
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const writes = [];
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    if (request.method() !== "GET") writes.push(request.method());
    const body = fixture[new URL(request.url()).pathname];
    await route.fulfill({ status: body ? 200 : 404, json: body ?? {} });
  });
  await page.goto(`${origin}/analysis/calls`, { waitUntil: "networkidle" });
  const row = page.locator(".calls-library-row").first();
  await row.waitFor();
  await page
    .getByText(
      fixture[`/v1/conversation/acquisition/submissions/${id}/report`].verdict,
      { exact: false },
    )
    .first()
    .waitFor();
  const closeGuide = page.getByRole("button", {
    name: "Close guide",
    exact: true,
  });
  if (await closeGuide.count()) await closeGuide.click();
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await row.scrollIntoViewIfNeeded();
    const result = await row.evaluate((element) => {
      const rect = (selector) => {
        const node = element.querySelector(selector);
        const r = node.getBoundingClientRect();
        const hit = document.elementFromPoint(
          r.x + r.width / 2,
          r.y + r.height / 2,
        );
        return {
          x: r.x,
          y: r.y,
          right: r.right,
          bottom: r.bottom,
          width: r.width,
          height: r.height,
          exposed: node.contains(hit),
        };
      };
      return {
        duration: rect(".calls-library-duration-clock"),
        slot: rect(".calls-library-duration"),
        status: rect(".calls-library-state"),
        item: rect(".calls-library-item"),
        text: element.querySelector(".calls-library-duration-clock")
          .textContent,
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    receipts.push({ width, ...result });
    if (output) {
      await mkdir(output, { recursive: true });
      await row.screenshot({ path: `${output}/calls-fixture-${width}.png` });
    }
    const { duration: d, status: s, slot, item } = result;
    assert.equal(result.text, "About 03:15");
    assert.ok(d.width > 0 && d.height > 0, "duration must be visible");
    assert.ok(d.exposed && s.exposed, "duration and status must be unobscured");
    assert.ok(
      slot.width >= d.width,
      "duration needs a slot wide enough for its text",
    );
    assert.ok(
      d.x >= slot.x && d.right <= slot.right + 0.5,
      "duration must fit its slot",
    );
    assert.ok(
      d.right <= s.x || s.right <= d.x || d.bottom <= s.y || s.bottom <= d.y,
      "duration and status must not overlap",
    );
    assert.ok(
      d.x >= item.x && s.right <= item.right,
      "duration and status must fit inside the card",
    );
    assert.equal(
      result.documentWidth,
      width,
      "page must not overflow horizontally",
    );
  }
  assert.deepEqual(writes, [], "fixture must not issue writes");
  console.log(
    JSON.stringify(
      { evidence: "fictional render fixture; not live acceptance", receipts },
      null,
      2,
    ),
  );
} finally {
  if (output)
    await writeFile(
      `${output}/calls-fixture-receipt.json`,
      JSON.stringify(
        { evidence: "fictional render fixture; not live acceptance", receipts },
        null,
        2,
      ),
    );
  await browser.close();
}
