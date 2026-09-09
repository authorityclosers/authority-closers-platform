// Bounded follow-up: one real synthetic gaps attempt, native CDP input, no saved appearance changes.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";

const resumeVisible = process.argv[2] === "--resume-visible-unanswered-gaps";
const suppliedAttempt = resumeVisible ? process.argv[3] : null;
if (suppliedAttempt && !/^[0-9a-f-]{36}$/.test(suppliedAttempt))
  process.exit(2);
if (process.argv[2] !== "--run-one-local-gaps-attempt" && !resumeVisible) {
  process.stdout.write(
    "Run only when authorized: --run-one-local-gaps-attempt. Creates at most one synthetic learner gaps attempt.\n",
  );
  process.exit(0);
}
const repository = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
if (
  repository.toLowerCase() !==
  "c:\\users\\suyash\\.codex\\worktrees\\d2de\\authority-closers-platform"
)
  process.exit(2);
const origin = "http://learner.localhost:3100";
const output = path.join(
  repository,
  "docs/evidence/screenshots",
  "practice-followup-" + new Date().toISOString().replace(/[:.]/g, "-"),
);
const deadline = Date.now() + 8 * 60_000;
const dimensions = [
  ["desktop1440", 1440, 1000],
  ["mobile390", 390, 844],
  ["mobile320", 320, 740],
];
const assert = (value) => {
  if (!value) throw Error("Acceptance condition failed");
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
let stage = "local document";
let page;
let originalTheme;
let mouseClicks = 0;
let keyboardEvents = 0;
const captures = [];
const get = (route, projection = "value") => {
  assert(Date.now() < deadline);
  assert(
    route === "/v1/me" ||
      route === "/v1/profile/avatar" ||
      route === "/v1/practice/progress" ||
      /^\/v1\/practice\/attempts\/[0-9a-f-]{36}$/.test(route),
  );
  return page.evaluate(
    `(async()=>{if(location.origin!==${JSON.stringify(origin)})throw Error();const r=await fetch(${JSON.stringify(route)},{credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error();const value=await r.json();return (${projection});})()`,
  );
};
const guard = async () =>
  assert(
    await get(
      "/v1/me",
      "value.email==='learner@ac.localhost'&&value.membership_role==='learner'&&value.selected_tenant_id==='65e76922-c033-5459-9101-3de86637246e'",
    ),
  );
const preferences = () =>
  page.evaluate(
    "['ac-appearance-theme','ac-appearance-accent','ac-appearance-density','ac-appearance-motion'].map(key=>localStorage.getItem(key))",
  );
const avatar = () =>
  get(
    "/v1/profile/avatar",
    "({asset:value.avatar?.asset_id??null,version:value.avatar?.version_id??null})",
  );
const progress = () => get("/v1/practice/progress");
const attempt = (id) => get(`/v1/practice/attempts/${id}`);
const observeInput = async () => {
  await page.evaluate(
    "(()=>{window.__acNativeProof={click:0,keydown:0};for(const type of ['click','keydown'])document.addEventListener(type,event=>{if(event.isTrusted)window.__acNativeProof[type]++},{capture:true});})()",
  );
};
const navigate = async (pathname) => {
  const previous = await page.evaluate("performance.timeOrigin");
  await page.send("Page.navigate", { url: origin + pathname });
  await page.until(
    `performance.timeOrigin!==${previous}&&location.origin===${JSON.stringify(origin)}&&document.readyState==='complete'`,
    60_000,
  );
  await page.send("Page.bringToFront");
  await page.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await observeInput();
};
const key = async (name, code) => {
  const before = await page.evaluate("window.__acNativeProof.keydown");
  for (const type of ["keyDown", "keyUp"])
    await page.send("Input.dispatchKeyEvent", {
      type,
      key: name,
      code: name,
      ...(type === "keyDown" && name === "Enter"
        ? { text: "\r", unmodifiedText: "\r" }
        : {}),
      windowsVirtualKeyCode: code,
      nativeVirtualKeyCode: code,
    });
  assert((await page.evaluate("window.__acNativeProof.keydown")) > before);
  keyboardEvents += 1;
  await page.delay(100);
};
const mouse = async (expression) => {
  await page.until(`Boolean(${expression})`);
  await page.evaluate(
    `${expression}.scrollIntoView({block:'center',inline:'nearest'})`,
  );
  await page.delay(120);
  const point = await page.evaluate(
    `(()=>{const e=${expression};const r=e.getBoundingClientRect();if(e.disabled||r.width<=0||r.height<=0)throw Error();return{x:r.left+r.width/2,y:r.top+r.height/2};})()`,
  );
  const before = await page.evaluate("window.__acNativeProof.click");
  await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    ...point,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    ...point,
    button: "left",
    buttons: 0,
    clickCount: 1,
  });
  assert((await page.evaluate("window.__acNativeProof.click")) > before);
  mouseClicks += 1;
};
const tabTo = async (expression) => {
  for (let index = 0; index < 18; index++) {
    if (await page.evaluate(`document.activeElement===(${expression})`)) return;
    await key("Tab", 9);
  }
  throw Error("Keyboard target unavailable");
};
const viewport = async (width, height) => {
  await page.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await page.delay(250);
};
const capture = async (name, action = null) => {
  const bounds = await page.evaluate(
    `(()=>{const d=document.documentElement;const s=document.querySelector('[data-session-scroll="body"]');const a=${action ?? "null"};const r=a?.getBoundingClientRect();return {available:d.clientWidth,width:d.scrollWidth,scrollFits:!s||s.scrollWidth<=s.clientWidth+1,actionFits:${Boolean(action)}?Boolean(r&&r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=d.clientWidth):true};})()`,
  );
  assert(
    bounds.width <= bounds.available + 1 &&
      bounds.scrollFits &&
      bounds.actionFits,
  );
  const image = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    path.join(output, name + ".png"),
    Buffer.from(image.data, "base64"),
    { flag: "wx" },
  );
  captures.push({ name, ...bounds });
};
const hub = async (prefix) => {
  await page.until(
    "Boolean(document.querySelector('[aria-label=\"Your saved practice\"]'))&&Boolean([...document.querySelectorAll('summary')].find(e=>e.textContent.trim()==='Your recent rewards'))",
  );
  const summary =
    "[...document.querySelectorAll('summary')].find(e=>e.textContent.trim()==='Your recent rewards')";
  if (!(await page.evaluate(`${summary}.parentElement.open`)))
    await mouse(summary);
  for (const [name, width, height] of dimensions) {
    await viewport(width, height);
    await page.evaluate(
      "document.querySelector('[aria-label=\"Your saved practice\"]').scrollIntoView({block:'start'})",
    );
    // Keep the wallet below the existing sticky app header in viewport evidence.
    await page.evaluate("window.scrollBy(0,-96)");
    await page.delay(150);
    await capture(`${prefix}-${name}`);
    if (width <= 390) {
      await page.evaluate(
        `${summary}.scrollIntoView({block:'start'});window.scrollBy(0,-96)`,
      );
      await page.delay(150);
      await capture(`${prefix}-recent-rewards-${name}`);
    }
  }
};
const restoreTheme = async () => {
  await page.send("Emulation.setEmulatedMedia", { features: [] });
  if (originalTheme)
    await page.evaluate(
      `(()=>{const value=${JSON.stringify(originalTheme)};const root=document.documentElement;for(const [key,item] of Object.entries(value.attributes)){if(item===null)root.removeAttribute(key);else root.setAttribute(key,item)}root.style.colorScheme=value.colorScheme;})()`,
    );
};

try {
  page = await localPage(
    suppliedAttempt
      ? {
          pathname: `/practice?set=gaps&attempt=${suppliedAttempt}`,
          newTab: true,
        }
      : resumeVisible
        ? {}
        : { pathname: "/practice", newTab: true },
  );
  await page.until(
    `location.origin===${JSON.stringify(origin)}&&location.pathname==='/practice'&&document.readyState==='complete'`,
    60_000,
  );
  await page.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await observeInput();
  await guard();
  const resumedId =
    suppliedAttempt ??
    (resumeVisible
      ? await page.evaluate(
          "new URL(location.href).searchParams.get('set')==='gaps'?new URL(location.href).searchParams.get('attempt'):null",
        )
      : null);
  if (resumeVisible) {
    assert(resumedId && /^[0-9a-f-]{36}$/.test(resumedId));
    const existing = await attempt(resumedId);
    assert(
      existing.set_id === "gaps" &&
        existing.state === "in_progress" &&
        existing.acknowledged_item_ids.length === 0 &&
        existing.item_states.every(
          (entry) => entry.response_id === null && entry.feedback === null,
        ),
    );
  }
  const beforePreferences = await preferences();
  const beforeAvatar = await avatar();
  const baseline = await progress();
  assert(
    baseline.profile.timezone &&
      baseline.purchases_enabled === false &&
      baseline.course_progress_affected === false,
  );
  await mkdir(output, { recursive: false });
  const completed = baseline.recent_attempts.find(
    (entry) => entry.state === "completed",
  );
  assert(completed);
  stage = "centered completed CTA";
  await navigate(`/practice?set=${completed.set_id}&attempt=${completed.id}`);
  await page.until("Boolean(document.querySelector('#practice-earned-title'))");
  await viewport(1440, 1000);
  const returnLink =
    "[...document.querySelectorAll('a')].find(e=>e.textContent.trim()==='Back to practice')";
  const center = await page.evaluate(
    `(()=>{const r=${returnLink}.getBoundingClientRect();return Math.abs(r.left+r.width/2-document.documentElement.clientWidth/2);})()`,
  );
  assert(center <= 2);
  await capture("01-centered-completion-desktop1440", returnLink);
  stage = "hub wallet rhythm and recent rewards";
  await navigate("/practice");
  await hub("02-hub-wallet");
  stage = "temporary dark and reduced motion";
  originalTheme = await page.evaluate(
    "({attributes:Object.fromEntries(['data-theme','data-theme-preference','data-reduced-motion'].map(key=>[key,document.documentElement.getAttribute(key)])),colorScheme:document.documentElement.style.colorScheme})",
  );
  await page.send("Emulation.setEmulatedMedia", {
    features: [
      { name: "prefers-color-scheme", value: "dark" },
      { name: "prefers-reduced-motion", value: "reduce" },
    ],
  });
  await page.delay(350);
  // The user's explicit light preference wins over system emulation. This temporary
  // DOM theme selector exercises existing dark CSS without changing stored preferences.
  await page.evaluate(
    "document.documentElement.setAttribute('data-theme','dark');document.documentElement.style.colorScheme='dark'",
  );
  await page.until(
    "matchMedia('(prefers-reduced-motion: reduce)').matches&&document.documentElement.dataset.theme==='dark'",
  );
  for (const [name, width, height] of [dimensions[0], dimensions[1]]) {
    await viewport(width, height);
    await page.evaluate(
      "document.querySelector('[aria-label=\"Your saved practice\"]').scrollIntoView({block:'start'})",
    );
    await page.evaluate("window.scrollBy(0,-96)");
    await capture(`03-hub-dark-reduced-${name}`);
  }
  assert(same(beforePreferences, await preferences()));
  await restoreTheme();
  originalTheme = null;
  stage = "one native gaps start";
  await navigate(
    resumedId
      ? `/practice?set=gaps&attempt=${resumedId}`
      : "/practice?set=gaps",
  );
  await viewport(390, 844);
  if (!resumedId) {
    await page.until(`Boolean(${page.button("Start a new practice")})`);
    await guard();
    await mouse(page.button("Start a new practice"));
  }
  await page.until(
    "/^[0-9a-f-]{36}$/.test(new URL(location.href).searchParams.get('attempt')??'')&&Boolean(document.querySelector('input[type=radio]'))",
  );
  const id = await page.evaluate(
    "new URL(location.href).searchParams.get('attempt')",
  );
  let saved = await attempt(id);
  assert(
    saved.set_id === "gaps" &&
      saved.set.items.length > 0 &&
      saved.set.items.length <= 6 &&
      saved.set.items.every((entry) => entry.kind === "gap"),
  );
  stage = "native exit dialog cancellation";
  const beforeExit = await attempt(id);
  await mouse(page.button("Leave practice"));
  await page.until("Boolean(document.querySelector('dialog[open]'))");
  assert(
    await page.evaluate(
      "document.querySelector('dialog').textContent.includes('No earned credits will be taken away.')&&document.querySelector('dialog').textContent.includes('Your confirmed responses are saved.')",
    ),
  );
  await capture("04-native-exit-warning-mobile390");
  await key("Escape", 27);
  await page.until(
    "!document.querySelector('dialog[open]')&&document.activeElement?.getAttribute('aria-label')==='Leave practice'",
  );
  await mouse(page.button("Leave practice"));
  await page.until("Boolean(document.querySelector('dialog[open]'))");
  await mouse(page.button("Keep practising"));
  await page.until(
    "!document.querySelector('dialog[open]')&&document.activeElement?.getAttribute('aria-label')==='Leave practice'",
  );
  assert(same(beforeExit, await attempt(id)));
  // Re-enter the same untouched attempt so its normal initial prompt focus is
  // asserted separately from the intentional exit-button focus restoration.
  await navigate(`/practice?set=gaps&attempt=${id}`);
  const inputProof = [];
  for (let index = 0; index < saved.set.items.length; index++) {
    stage = "native gap choice and keyboard change";
    await page.until(
      "document.activeElement?.id.startsWith('prompt-')&&Boolean(document.querySelector('input[type=radio]:not(:disabled)'))",
    );
    await guard();
    await mouse("document.querySelector('input[type=radio]').closest('label')");
    await page.until("document.querySelector('input[type=radio]').checked");
    await key("ArrowDown", 40);
    await page.until(
      "[...document.querySelectorAll('input[type=radio]')][1]?.checked",
    );
    const selected = await page.evaluate(
      "Number(document.querySelector('input[type=radio]:checked').value)",
    );
    await tabTo(page.button("Check my response"));
    await key("Enter", 13);
    await page.until("document.activeElement?.getAttribute('role')==='status'");
    const answered = await attempt(id);
    const itemState = answered.item_states.find(
      (entry) => !entry.acknowledged && entry.feedback?.kind === "feedback",
    );
    assert(
      itemState &&
        same(itemState.selections, [selected]) &&
        answered.acknowledged_item_ids.length === index &&
        answered.reward_receipts.length === 0,
    );
    const advance =
      index === saved.set.items.length - 1 ? "Finish this set" : "Next prompt";
    if (index === 0)
      await capture("04-native-gap-feedback-mobile390", page.button(advance));
    stage = "native feedback acknowledgement";
    await guard();
    await tabTo(page.button(advance));
    await key("Enter", 13);
    await page.until(
      index === saved.set.items.length - 1
        ? "Boolean(document.querySelector('#practice-earned-title'))"
        : `document.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow')==='${index + 1}'&&document.activeElement?.id.startsWith('prompt-')`,
    );
    saved = await attempt(id);
    assert(saved.acknowledged_item_ids.length === index + 1);
    inputProof.push({
      chose_by_mouse: true,
      changed_by_arrow_key: true,
      submitted_by_keyboard: true,
      feedback_focused: true,
      acknowledged_by_keyboard: true,
    });
  }
  assert(
    saved.state === "completed" &&
      saved.completed_at &&
      saved.responses_stored === true &&
      saved.course_progress_affected === false,
  );
  assert(
    saved.reward_receipts.length === 1 &&
      saved.reward_receipts[0].kind === "daily_set" &&
      saved.reward_receipts[0].credits === 10 &&
      saved.reward_receipts[0].xp === 30,
  );
  const after = await progress();
  assert(
    after.credits_balance === baseline.credits_balance + 10 &&
      after.xp_total === baseline.xp_total + 30 &&
      after.actual_practice_days_this_week ===
        baseline.actual_practice_days_this_week,
  );
  await capture("05-second-family-completed-mobile390");
  stage = "completion reduced-motion CSS";
  await page.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });
  await page.until("matchMedia('(prefers-reduced-motion: reduce)').matches");
  assert(
    await page.evaluate(
      "getComputedStyle(document.querySelector('[class*=completionMark]')).animationName==='none'",
    ),
  );
  await page.send("Emulation.setEmulatedMedia", { features: [] });
  stage = "final hub and invariants";
  await navigate("/practice");
  await hub("06-hub-after-second-family");
  await guard();
  assert(
    same(beforePreferences, await preferences()) &&
      same(beforeAvatar, await avatar()),
  );
  assert(page.external() === 0);
  const result = {
    status: "passed",
    centered_completion_cta_error_px: center,
    native_cdp_mouse_clicks: mouseClicks,
    native_cdp_key_actions: keyboardEvents,
    prompts: inputProof,
    second_family_credits: 10,
    second_family_xp: 30,
    practice_day_count_unchanged: true,
    temporary_dark_css: true,
    reduced_motion_animation_none: true,
    saved_preferences_and_avatar_unchanged: true,
    external_requests: 0,
    physical_device_certification: false,
    resumed_existing_unanswered_attempt: Boolean(resumedId),
    native_exit_escape_and_cancel_focus_return: true,
    captures,
  };
  await writeFile(
    path.join(output, "proof.json"),
    JSON.stringify(result, null, 2) + "\n",
    { flag: "wx" },
  );
  process.stdout.write(
    JSON.stringify({
      ...result,
      prompts: inputProof.length,
      captures: captures.length,
      output,
    }) + "\n",
  );
} catch {
  process.stderr.write(
    `Local practice follow-up incomplete at ${stage}; no private diagnostics emitted.\n`,
  );
  process.exitCode = 1;
} finally {
  if (page) {
    await restoreTheme().catch(() => {});
    await page
      .send("Emulation.setFocusEmulationEnabled", { enabled: false })
      .catch(() => {});
    await page.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
    await page.close();
  }
}
