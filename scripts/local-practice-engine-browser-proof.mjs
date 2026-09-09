// Prepared local acceptance. Run only after the coordinator confirms engine activation.
// Uses the existing disposable Chrome session; never reads credentials or cookies.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";

const RUN = "--run-activated-local-fixture";
if (process.argv.length !== 3 || process.argv[2] !== RUN) {
  process.stdout.write(
    `Prepared only. After explicit runtime activation: node scripts/local-practice-engine-browser-proof.mjs ${RUN}\n` +
      "Uses the signed-in synthetic learner; at most two real practice attempts, with explicit initial practice timezone setup only if absent. No service, identity, avatar or appearance changes.\n",
  );
  process.exit(
    process.argv[2] === "--help" || process.argv.length === 2 ? 0 : 2,
  );
}

const repository = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const expectedRepository =
  "C:\\Users\\Suyash\\.codex\\worktrees\\d2de\\authority-closers-platform";
if (repository.toLowerCase() !== expectedRepository.toLowerCase()) {
  process.stderr.write(
    "This proof is limited to the reviewed local worktree.\n",
  );
  process.exit(2);
}
const origin = "http://learner.localhost:3100";
const academy = "65e76922-c033-5459-9101-3de86637246e";
const setId = "next-move";
const startPath = `/practice?set=${setId}`;
const dimensions = [
  ["desktop1440", 1440, 1000],
  ["mobile390", 390, 844],
  ["mobile320", 320, 740],
];
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const output = path.join(
  repository,
  "docs/evidence/screenshots",
  `practice-engine-${stamp}`,
);
const deadline = Date.now() + 8 * 60_000;
let stage = "preflight";
let page;
let issuedCount = 0;
let responseCount = 0;
let acknowledgementCount = 0;
const captures = [];
const assert = (condition) => {
  if (!condition) throw new Error("Acceptance condition failed");
};
const bounded = () => assert(Date.now() < deadline);
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const attemptPath = (id) => `${startPath}&attempt=${encodeURIComponent(id)}`;

// All diagnostic requests are authenticated read-only same-origin projections.
// Mutations below are exclusively the rendered product's buttons and input events.
const get = async (route, project = "value") => {
  bounded();
  assert(
    route === "/v1/me" ||
      route === "/v1/profile/avatar" ||
      route === "/v1/practice/progress" ||
      /^\/v1\/practice\/attempts\/[0-9a-f-]{36}$/.test(route),
  );
  return page.evaluate(`(async()=>{
    if(location.origin!==${JSON.stringify(origin)})throw Error();
    const response=await fetch(${JSON.stringify(route)},{credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error();
    const value=await response.json(); return (${project});
  })()`);
};
const guard = async () =>
  assert(
    await get(
      "/v1/me",
      `value.email==='learner@ac.localhost' && value.selected_tenant_id===${JSON.stringify(academy)} && value.membership_role==='learner'`,
    ),
  );
const appearance = () =>
  page.evaluate(
    "({theme:localStorage.getItem('ac-appearance-theme'),accent:localStorage.getItem('ac-appearance-accent')})",
  );
const avatar = () =>
  get(
    "/v1/profile/avatar",
    "({asset:value.avatar?.asset_id??null,version:value.avatar?.version_id??null})",
  );
const progress = () => get("/v1/practice/progress");
const readAttempt = (id) => get(`/v1/practice/attempts/${id}`);
const wallet = (value) => ({
  credits: value.credits_balance,
  xp: value.xp_total,
  days: value.actual_practice_days_this_week,
  receipts: value.recent_awards.map((item) => item.id).sort(),
});
const invariantFlags = (value) =>
  assert(
    value.course_progress_affected === false &&
      ("purchases_enabled" in value
        ? value.purchases_enabled === false
        : value.responses_stored === true),
  );
const navigate = async (pathname) => {
  bounded();
  const previous = await page.evaluate("performance.timeOrigin");
  await page.send("Page.navigate", { url: origin + pathname });
  await page.until(
    `performance.timeOrigin!==${previous} && document.readyState==='complete'`,
    60_000,
  );
};
const reload = async () => {
  const previous = await page.evaluate("performance.timeOrigin");
  await page.send("Page.reload");
  await page.until(
    `performance.timeOrigin!==${previous} && document.readyState==='complete'`,
    60_000,
  );
};
const readyAttempt = async (value) => {
  const next = value.set.items.find(
    (item) => !value.acknowledged_item_ids.includes(item.id),
  );
  if (value.state === "completed")
    await page.until(
      "Boolean(document.querySelector('#practice-earned-title'))",
    );
  else
    await page.until(
      `Boolean(document.getElementById(${JSON.stringify(`prompt-${next.id}`)}))`,
    );
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
  bounded();
  const result = await page.evaluate(`(()=>{
    const root=document.documentElement;
    const scroll=document.querySelector('[data-session-scroll="body"]');
    const action=${action ? page.button(action) : "null"};
    const bounds=action?.getBoundingClientRect();
    return {available:root.clientWidth,width:root.scrollWidth,
      bodyFits:!scroll||scroll.scrollWidth<=scroll.clientWidth+1,
      actionFits:${Boolean(action)}?Boolean(bounds&&bounds.top>=0&&bounds.bottom<=innerHeight&&bounds.left>=0&&bounds.right<=root.clientWidth):true};
  })()`);
  assert(
    result.width <= result.available + 1 &&
      result.bodyFits &&
      result.actionFits,
  );
  const image = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    path.join(output, `${name}.png`),
    Buffer.from(image.data, "base64"),
    { flag: "wx" },
  );
  captures.push({ name, ...result });
};
const responsive = async (name, action = null) => {
  for (const [label, width, height] of dimensions) {
    await viewport(width, height);
    await capture(`${name}-${label}`, action);
  }
  await viewport(390, 844);
};
const savedFeedback = async (value, item) => {
  const itemState = value.item_states.find(
    (entry) => entry.item_id === item.id,
  );
  assert(
    itemState?.feedback?.kind === "feedback" &&
      itemState.response_id &&
      !itemState.acknowledged,
  );
  await page.until(
    `Boolean(${page.button(value.acknowledged_item_ids.length === value.set.items.length - 1 ? "Finish this set" : "Next prompt")})`,
  );
  await page.until(
    `document.body.textContent.includes(${JSON.stringify(itemState.feedback.explanation)})`,
  );
};
const start = async (allowInitialTimezone) => {
  bounded();
  await guard();
  const before = await progress();
  invariantFlags(before);
  const startLabel = before.profile.timezone
    ? "Start a new practice"
    : "Save timezone & start";
  await page.until(`Boolean(${page.button(startLabel)})`);
  if (!before.profile.timezone) {
    assert(allowInitialTimezone);
    await page.until(
      "Boolean(document.querySelector('input[list=practice-timezones]:not(:disabled)'))",
    );
    await page.evaluate(
      "(()=>{const input=document.querySelector('input[list=practice-timezones]');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'Asia/Kolkata');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));})()",
      true,
    );
    await page.until(
      "document.querySelector('input[list=practice-timezones]')?.value==='Asia/Kolkata'",
    );
  }
  if (issuedCount === 0) await responsive("01-start", startLabel);
  await guard();
  assert(issuedCount < 2);
  await page.click(startLabel);
  issuedCount += 1;
  await page.until(
    "/^[0-9a-f-]{36}$/.test(new URL(location.href).searchParams.get('attempt')??'')",
  );
  const id = await page.evaluate(
    "new URL(location.href).searchParams.get('attempt')",
  );
  const value = await readAttempt(id);
  invariantFlags(value);
  assert(
    value.set_id === setId &&
      value.state === "in_progress" &&
      value.acknowledged_item_ids.length === 0 &&
      value.reward_receipts.length === 0,
  );
  assert(
    value.set.items.length > 0 &&
      value.set.items.length <= 6 &&
      value.set.items.every((item) => item.kind === "choice"),
  );
  const after = await progress();
  assert(same(wallet(before), wallet(after)));
  assert(
    before.profile.timezone
      ? same(before.profile, after.profile)
      : after.profile.timezone === "Asia/Kolkata",
  );
  await readyAttempt(value);
  return value;
};
const complete = async (initial, baseline, detailed) => {
  let value = initial;
  for (let index = 0; index < initial.set.items.length; index++) {
    bounded();
    const item = value.set.items.find(
      (entry) => !value.acknowledged_item_ids.includes(entry.id),
    );
    assert(item);
    await readyAttempt(value);
    await page.until(
      "Boolean(document.querySelector('input[type=radio]:not(:disabled)'))",
    );
    await guard();
    await page.evaluate(
      "document.querySelector('input[type=radio]:not(:disabled)').click()",
      true,
    );
    if (detailed && index === 0)
      await responsive("02-selected", "Check my response");
    await page.click("Check my response");
    responseCount += 1;
    await page.until(
      `Boolean(${page.button(index === initial.set.items.length - 1 ? "Finish this set" : "Next prompt")})`,
    );
    let answered = await readAttempt(value.id);
    invariantFlags(answered);
    assert(
      answered.revision > value.revision &&
        answered.acknowledged_item_ids.length === index &&
        answered.reward_receipts.length === 0,
    );
    await savedFeedback(answered, item);
    assert(same(wallet(await progress()), wallet(baseline)));
    if (detailed && index === 0) {
      await responsive(
        "03-feedback",
        initial.set.items.length === 1 ? "Finish this set" : "Next prompt",
      );
      stage = "saved-feedback reload";
      await reload();
      await readyAttempt(answered);
      await savedFeedback(answered, item);
      const resumed = await readAttempt(answered.id);
      assert(same(answered, resumed));
      await capture(
        "04-feedback-resumed-mobile390",
        initial.set.items.length === 1 ? "Finish this set" : "Next prompt",
      );
    }
    stage = detailed
      ? "first attempt acknowledgement"
      : "replay acknowledgement";
    await guard();
    await page.click(
      index === initial.set.items.length - 1
        ? "Finish this set"
        : "Next prompt",
    );
    acknowledgementCount += 1;
    await page.until(
      index === initial.set.items.length - 1
        ? "Boolean(document.querySelector('#practice-earned-title'))"
        : `document.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow')==='${index + 1}'`,
    );
    value = await readAttempt(answered.id);
    invariantFlags(value);
    assert(
      value.revision > answered.revision &&
        value.acknowledged_item_ids.length === index + 1,
    );
    if (detailed && index === 0 && value.state !== "completed") {
      stage = "acknowledged prompt reload";
      await reload();
      await readyAttempt(value);
      assert(same(value, await readAttempt(value.id)));
      await capture("05-next-prompt-resumed-mobile390", "Check my response");
    }
    if (value.state !== "completed")
      assert(same(wallet(await progress()), wallet(baseline)));
  }
  assert(
    value.state === "completed" &&
      value.completed_at &&
      value.acknowledged_item_ids.length === value.set.items.length,
  );
  return value;
};

try {
  page = await localPage({ pathname: startPath, newTab: true });
  stage = "new document readiness";
  // A newly created Chrome target can briefly expose a complete about:blank.
  await page.until(
    `location.origin===${JSON.stringify(origin)} && location.pathname==='/practice' && document.readyState==='complete'`,
    60_000,
  );
  stage = "synthetic identity guard";
  await guard();
  stage = "read-only avatar baseline";
  const initialAvatar = await avatar();
  stage = "read-only appearance baseline";
  const initialAppearance = await appearance();
  stage = "practice progress baseline";
  const initialProgress = await progress();
  invariantFlags(initialProgress);
  stage = "new evidence directory";
  await mkdir(output, { recursive: false });
  stage = "first attempt start";
  const first = await start(true);
  const baseline = await progress();
  const localDay = () =>
    page.evaluate(
      `new Intl.DateTimeFormat('en-CA',{timeZone:${JSON.stringify(baseline.profile.timezone)},year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())`,
    );
  const beganDay = await localDay();
  stage = "first attempt response";
  const completed = await complete(first, baseline, true);
  stage = "completed receipt verification";
  const afterFirst = await progress();
  invariantFlags(afterFirst);
  assert(
    afterFirst.credits_balance - baseline.credits_balance ===
      completed.reward_receipts.reduce(
        (sum, receipt) => sum + receipt.credits,
        0,
      ),
  );
  assert(
    afterFirst.xp_total - baseline.xp_total ===
      completed.reward_receipts.reduce((sum, receipt) => sum + receipt.xp, 0),
  );
  assert(
    completed.reward_receipts.every(
      (receipt) =>
        !baseline.recent_awards.some((existing) => existing.id === receipt.id),
    ),
  );
  await responsive("06-completed");
  stage = "completed attempt reopen";
  await navigate(attemptPath(completed.id));
  await readyAttempt(completed);
  assert(same(completed, await readAttempt(completed.id)));
  assert(same(wallet(afterFirst), wallet(await progress())));
  await capture("07-completed-reopened-mobile390");
  stage = "same-family replay start";
  await navigate(startPath);
  const replay = await start(false);
  assert(replay.id !== completed.id);
  stage = "same-family replay response";
  const replayCompleted = await complete(replay, afterFirst, false);
  assert(replayCompleted.reward_receipts.length === 0);
  assert(same(wallet(afterFirst), wallet(await progress())));
  assert((await localDay()) === beganDay);
  await responsive("08-replay-no-new-reward");
  stage = "final read-only invariants";
  await guard();
  assert(
    same(initialAvatar, await avatar()) &&
      same(initialAppearance, await appearance()),
  );
  assert(page.external() === 0);
  const proof = {
    status: "passed",
    attempts_started: issuedCount,
    responses: responseCount,
    acknowledgements: acknowledgementCount,
    saved_feedback_and_prompt_reload: true,
    completed_reopen_unchanged: true,
    same_family_replay_added_no_award: true,
    server_receipt_wallet_delta_matches: true,
    purchases_disabled: true,
    course_progress_affected: false,
    avatar_and_appearance_unchanged: true,
    initial_timezone_saved: initialProgress.profile.timezone === null,
    external_requests: 0,
    native_input_certification: false,
    captures,
  };
  await writeFile(
    path.join(output, "proof.json"),
    JSON.stringify(proof, null, 2) + "\n",
    { flag: "wx" },
  );
  process.stdout.write(
    JSON.stringify({ ...proof, captures: captures.length, output }) + "\n",
  );
} catch {
  process.stderr.write(
    `Local practice engine proof incomplete at ${stage}; no private diagnostics emitted.\n`,
  );
  process.exitCode = 1;
} finally {
  await page?.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
  await page?.close(); // Leaves the user's dedicated local Chrome tab open.
}
