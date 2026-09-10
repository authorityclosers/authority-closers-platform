import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import assert from "node:assert/strict";
import { localPage } from "./local-page-cdp.mjs";

if (!process.argv.includes("--acknowledge-local-draft-test"))
  throw new Error("Explicit sandbox draft test required");
const sandbox = JSON.parse(
  await readFile(".tmp/local-platform/sandbox.json", "utf8"),
);
const password = process.env.AC_LOCAL_BROWSER_TEST_PASSWORD;
if (!password) throw new Error("Local test credential required");
const origin = "http://coach.localhost:3102";
const page = await localPage({
  surface: "coach",
  pathname: "/login",
  newTab: true,
});
const checks = [];
const output = resolve(
  "docs/evidence/screenshots/coach-split-" +
    new Date().toISOString().replaceAll(":", "-"),
);
await mkdir(output, { recursive: true });
async function clickExpression(expression) {
  await page.until(`Boolean(${expression}) && !(${expression}).disabled`);
  await page.evaluate(`(${expression}).scrollIntoView({block:"center"})`);
  const point = await page.evaluate(
    `(() => {const r=(${expression}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`,
  );
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    button: "left",
    clickCount: 1,
    ...point,
  });
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    button: "left",
    clickCount: 1,
    ...point,
  });
}
async function fill(selector, value) {
  await clickExpression(`document.querySelector(${JSON.stringify(selector)})`);
  await page.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "a",
    code: "KeyA",
    modifiers: 2,
    windowsVirtualKeyCode: 65,
  });
  await page.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "a",
    code: "KeyA",
    modifiers: 2,
    windowsVirtualKeyCode: 65,
  });
  await page.send("Input.insertText", { text: value });
}
async function screenshot(name) {
  const result = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    resolve(output, name + ".png"),
    Buffer.from(result.data, "base64"),
  );
}
try {
  await page.until(
    "document.querySelector('button[type=submit],button.dev-admin-login-submit') && !document.querySelector('button.dev-admin-login-submit').disabled",
  );
  await fill("[name=email]", "coach@ac.localhost");
  await fill("[name=password]", password);
  await fill("[name=tenant_id]", sandbox.academy_tenant_id);
  await clickExpression(page.button("Sign in"));
  await page.until(
    "location.pathname === '/studio/programs' && document.body.innerText.includes('Open program')",
  );
  checks.push("normal Coach password login and persisted tenant context");
  const identity = await page.evaluate(
    "Promise.all(['/v1/me','/v1/me/studio-access'].map(path=>fetch(path).then(r=>r.json()))).then(([me,scope])=>({role:me.membership_role,permissions:me.permissions,tenant:scope.tenant_id,capabilities:scope.studio_capabilities}))",
  );
  assert.equal(identity.tenant, sandbox.academy_tenant_id);
  assert.equal(identity.role, "learner");
  assert.deepEqual(identity.permissions, []);
  assert.ok(
    identity.capabilities.every(
      (item) => item.program_id === sandbox.studio_program_id,
    ),
  );
  checks.push(
    "Coach grants do not imply Platform Admin or unrestricted catalog access",
  );
  await clickExpression(
    `document.querySelector('a[href="/studio/programs/${sandbox.studio_program_id}"]')`,
  );
  await page.until("Boolean(document.querySelector('[data-studio-editor]'))");
  const before = await page.evaluate(
    `fetch('/v1/admin/studio/programs/${sandbox.studio_program_id}').then(r=>r.json())`,
  );
  assert.equal(before.id, sandbox.studio_program_id);
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await screenshot("01-before-desktop");
  await clickExpression(page.button("Add module"));
  await page.until(`Boolean(document.querySelector('input[maxlength="200"]'))`);
  const title = "Local release proof " + new Date().toISOString().slice(0, 19);
  await fill('input[maxlength="200"]', title);
  await clickExpression(
    "document.querySelector('[data-studio-editor] form button[type=submit]')",
  );
  await page.until("Boolean(document.querySelector('[data-state=saved]'))");
  const after = await page.evaluate(
    `fetch('/v1/admin/studio/programs/${sandbox.studio_program_id}').then(r=>r.json())`,
  );
  const created = after.versions
    .flatMap((v) => v.modules)
    .filter((m) => m.title === title);
  assert.equal(created.length, 1);
  assert.equal(
    after.versions.flatMap((v) => v.modules).length,
    before.versions.flatMap((v) => v.modules).length + 1,
  );
  checks.push(
    "native UI append command persisted exactly one module in the synthetic draft",
  );
  const denied = await page.evaluate(
    "fetch('/v1/admin/enrollment-grants',{method:'POST',headers:{'content-type':'application/json'},body:'{}'}).then(r=>r.status)",
  );
  assert.equal(denied, 403);
  checks.push("operational grant denied on Coach origin");
  for (const width of [1440, 768, 390, 320]) {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width,
      height: 900,
      deviceScaleFactor: 1,
      mobile: width < 768,
    });
    await page.delay(200);
    const dimensions = await page.evaluate(
      "({viewport:innerWidth,document:document.documentElement.scrollWidth})",
    );
    assert.ok(
      dimensions.document <= dimensions.viewport,
      "No horizontal page overflow at " + width,
    );
    await screenshot("02-editor-" + width);
    checks.push(
      "editor fits " + width + "px without horizontal document overflow",
    );
  }
  assert.equal(page.external(), 0);
  await page.send("Emulation.clearDeviceMetricsOverride");
  await writeFile(
    resolve(output, "proof.json"),
    JSON.stringify(
      {
        scope: "actual isolated localhost Coach",
        production: false,
        checks,
        externalRequests: 0,
        fixtureProgram: sandbox.studio_program_id,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ status: "passed", checks: checks.length, output }),
  );
} catch {
  await screenshot("incomplete-current-state").catch(() => {});
  console.log(JSON.stringify({ status: "incomplete", checks, output }));
  process.exitCode = 1;
} finally {
  await page.close();
}
