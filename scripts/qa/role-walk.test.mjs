// node --test scripts/qa/role-walk.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { HOME, ROLES, SIZES, judge, plan, reportMarkdown, walkable } from "./role-walk.mjs";

const fine = { text: "Leads\nTo Call 4 Follow-ups 2 All Leads 34", errors: [], serverErrors: [], status: 200, home: false };

test("four fictional roles on a phone and a laptop; never a real person's sign-in", () => {
  assert.deepEqual(Object.keys(ROLES), ["owner", "admin", "manager", "seller"]);
  // Never the real owner's dev account (the proxy's "owner" alias), and each stays in a TEST or sandbox workspace.
  assert.ok(!Object.values(ROLES).some((role) => role.alias === "owner"));
  for (const role of [ROLES.owner, ROLES.manager, ROLES.seller]) assert.match(role.workspace, /^TEST · /);
  assert.equal(SIZES.phone.width, 360);
  assert.equal(SIZES.laptop.width, 1280);
});

test("the walk follows in-app pages only", () => {
  assert.equal(walkable("/leads?tab=all#x"), "/leads?tab=all");
  for (const href of ["https://example.com", "//evil.test", "/v1/me", "/__as/owner", "/sign-out", "/report.pdf", "", null])
    assert.equal(walkable(href), null, String(href));
});

test("the plan starts at Home, drops repeats and keeps one page of each kind", () => {
  const a = "00000000-0000-4000-8000-000000000300";
  const b = "00000000-0000-4000-8000-000000000301";
  assert.deepEqual(
    plan(["/leads", HOME, "/leads", `/analysis/calls/${a}`, `/analysis/calls/${b}`, `/leads?lead=${a}`, `/leads?lead=${b}`, "/growth"]),
    [HOME, "/leads", `/analysis/calls/${a}`, `/leads?lead=${a}`, "/growth"],
  );
  assert.equal(plan(["/a", "/b", "/c"], 2).length, 2);
});

test("a page fails on what a person would hit", () => {
  assert.equal(judge(fine), null);
  assert.equal(judge({ ...fine, text: "You don't have access to Billing. Ask your admin." }), "a refusal page");
  assert.equal(
    judge({ ...fine, text: "You don't have access to this page", home: true }),
    "the role's own home page is refused",
  );
  assert.equal(judge({ ...fine, text: "Something went wrong" }), "an error page");
  assert.equal(judge({ ...fine, text: "New analysis Accept our terms to continue" }), "the terms box covers the page");
  assert.equal(judge({ ...fine, text: "  \n " }), "a blank page");
  assert.equal(judge({ ...fine, text: `${fine.text}\nOwner: undefined` }), "junk on screen");
  assert.equal(judge({ ...fine, errors: ["x is not a function"] }), "uncaught error: x is not a function");
  assert.equal(judge({ ...fine, serverErrors: ["500 on /v1/me"] }), "API 500 on /v1/me");
  assert.equal(judge({ ...fine, status: 404 }), "HTTP 404");
});

test("the report counts pages per role and lists what failed", () => {
  const rows = [
    { role: "seller", size: "phone", path: HOME },
    { role: "seller", size: "phone", path: "/billing", note: "a refusal page" },
  ];
  const report = reportMarkdown(rows);
  assert.match(report, /\| seller \| phone \| 2 \| 1 \|/);
  assert.match(report, /\| seller \| phone \| `\/billing` \| a refusal page \|/);
  assert.match(reportMarkdown([rows[0]]), /Every page each role is shown opened/);
});
