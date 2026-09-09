// Opt-in native-input acceptance only. Never starts Chrome, signs in, or restarts services.
// Owns a NEW tab; never attaches to a user's existing learner tab.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";

const renewalProof = process.argv[2] === "--run-authorized-local-renewal-proof";
const surfaceProof = process.argv[2] === "--run-authorized-local-surface-proof";
if (process.argv.length !== 3 || (!renewalProof && !surfaceProof && process.argv[2] !== "--run-authorized-local-hls-proof")) {
  process.stdout.write("Requires an already-running, normally signed-in synthetic learner Chrome on local CDP. Explicit opt-in: --run-authorized-local-hls-proof. No browser/server launch or login is performed.\n");
  process.exit(0);
}
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (repository.toLowerCase() !== "c:\\users\\suyash\\.codex\\worktrees\\d2de\\authority-closers-platform") {
  process.stderr.write("Refused: this proof is restricted to the designated local worktree.\n");
  process.exit(2);
}
const ORIGIN = "http://learner.localhost:3100";
const ACTIVITY = "2dbf0371-8456-5610-bb2f-629968a8e22d";
const TENANT = "65e76922-c033-5459-9101-3de86637246e";
const PLAYER = '.momentum-video-player[data-playback-mode="read-only"]';
const VIDEO = `${PLAYER} video`;
const QUALITY = '#momentum-video-settings select[aria-label="Video quality"]';
const RATE = '#momentum-video-settings select[aria-label="Playback speed"]';
const POSITION = `${PLAYER} input[aria-label="Lesson position"]`;
const output = path.join(repository, "docs/evidence/screenshots", `native-adaptive-video-${new Date().toISOString().replace(/[:.]/g, "-")}`);
const deadline = Date.now() + 10 * 60_000;
let page;
let stage = "connect-owned-tab";
let identityVerified = false;
let readonlyVerified = false;
let scriptId;
let artifactStarted = false;
const proof = {
  status: "incomplete", activity_id: ACTIVITY,
  interaction: surfaceProof ? "Native CDP mouse, keyboard and emulated touch" : "CDP Input.dispatchMouseEvent and Input.dispatchKeyEvent only",
  scope: "new synthetic-learner tab; no login, profile, preference, attempt or evidence mutation",
  mutation_observation: "main-document fetch/XHR/beacon/form guards; not a worker/browser-wide network certificate",
  not_covered: ["bandwidth-induced Auto adaptation", "Safari native HLS", ...(renewalProof ? ["live revocation", "tracked watch policy"] : ["grant expiry and revocation"]), "offline recovery"],
  checks: [], captures: [], input: { mouse: 0, keyboard: 0 },
};
class ProofFailure extends Error { constructor(code) { super("Local acceptance failed"); this.code = code; } }
const assert = (condition, code = "acceptance_condition_failed") => { if (!condition) throw new ProofFailure(code); };
const check = (name, observation = true) => { proof.checks.push({ name, observation }); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const element = (selector) => `document.querySelector(${JSON.stringify(selector)})`;
const button = (label) => `[...document.querySelectorAll(${JSON.stringify(`${PLAYER} button`)})].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)})`;
const settingsButton = (label) => `[...document.querySelectorAll('#momentum-video-settings button')].find(e=>e.textContent.trim()===${JSON.stringify(label)})`;

// Read-only browser instrumentation, installed before the activity document loads.
// It records COUNTS only, never URLs, headers, request bodies, tokens, or identities.
const guardSource = `(()=>{
  if(location.origin!==${JSON.stringify(ORIGIN)}||window.__acHlsProof)return;
  const state={blockedWrites:0,blockedExternal:0,trustedClicks:0,trustedMouseDowns:0,trustedKeys:0,trustedChanges:0,mediaGrants:0,firstMediaExpiry:0};
  const grants=new Set();let firstManifest=null;
  const originalFetch=window.fetch, originalOpen=XMLHttpRequest.prototype.open, originalSend=XMLHttpRequest.prototype.send;
  const originalBeacon=navigator.sendBeacon; const requests=new WeakMap();
  const allowed=(url,method)=>{let parsed;try{parsed=new URL(url,location.href)}catch{return false}
    if(parsed.origin!==location.origin){state.blockedExternal++;return false}
    if(!['GET','HEAD'].includes(String(method).toUpperCase())){state.blockedWrites++;return false}
    if(parsed.pathname.startsWith('/v1/media/playback/')){try{const token=parsed.searchParams.get('token');const encoded=token?.split('.')[1];const claim=JSON.parse(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')));
      if(claim.key.endsWith('/hls/master.m3u8')&&Number.isSafeInteger(claim.exp)&&typeof claim.delivery_grant_id==='string'){
        grants.add(claim.delivery_grant_id);state.mediaGrants=grants.size;if(!firstManifest){firstManifest=parsed.href;state.firstMediaExpiry=claim.exp*1000}}}catch{}}
    return true};
  window.fetch=function(input,init){const isRequest=input instanceof Request;const url=isRequest?input.url:String(input);const method=init?.method??(isRequest?input.method:'GET');
    if(!allowed(url,method))return Promise.reject(new TypeError('Read-only local proof refused request'));
    return originalFetch.call(this,input,init)};
  XMLHttpRequest.prototype.open=function(method,url,...rest){requests.set(this,{method,url:String(url)});return originalOpen.call(this,method,url,...rest)};
  XMLHttpRequest.prototype.send=function(body){const request=requests.get(this);if(!request||!allowed(request.url,request.method))throw new DOMException('Read-only local proof refused request','AbortError');return originalSend.call(this,body)};
  navigator.sendBeacon=function(){state.blockedWrites++;return false};
  const submit=e=>{state.blockedWrites++;e.preventDefault();e.stopImmediatePropagation()};
  const input=e=>{if(e.isTrusted){if(e.type==='click')state.trustedClicks++;if(e.type==='mousedown')state.trustedMouseDowns++;if(e.type==='keydown')state.trustedKeys++;if(e.type==='change')state.trustedChanges++}};
  document.addEventListener('submit',submit,true);for(const type of ['click','mousedown','keydown','change'])document.addEventListener(type,input,true);
  window.__acHlsProof=state;
  window.__acHlsProofExpired=async()=>{if(!firstManifest||Date.now()<state.firstMediaExpiry)throw Error();const r=await originalFetch(firstManifest,{credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});await r.body?.cancel();return r.status};
  window.__acHlsProofCleanup=()=>{window.fetch=originalFetch;XMLHttpRequest.prototype.open=originalOpen;XMLHttpRequest.prototype.send=originalSend;navigator.sendBeacon=originalBeacon;
    document.removeEventListener('submit',submit,true);for(const type of ['click','mousedown','keydown','change'])document.removeEventListener(type,input,true);delete window.__acHlsProof;delete window.__acHlsProofExpired;delete window.__acHlsProofCleanup};
})()`;

const readApi = async (route, projection) => {
  assert(Date.now() < deadline, "proof_deadline");
  assert(route === "/v1/me" || route === `/v1/activities/${ACTIVITY}`, "read_route_not_allowed");
  return page.evaluate(`(async()=>{if(location.origin!==${JSON.stringify(ORIGIN)})throw Error();const response=await fetch(${JSON.stringify(route)},{credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});if(!response.ok)throw Error();const value=await response.json();return (${projection})})()`);
};
const identityGuard = async () => assert(await readApi("/v1/me", `value.email==='learner@ac.localhost'&&value.membership_role==='learner'&&value.selected_tenant_id===${JSON.stringify(TENANT)}`), "synthetic_learner_required");
const activitySnapshot = () => readApi(`/v1/activities/${ACTIVITY}`, `(()=>{
  if(value.id!==${JSON.stringify(ACTIVITY)}||String(value.kind).toLowerCase()!=='video'||!['available','in_progress'].includes(String(value.state).toLowerCase())
    ||!Number.isSafeInteger(value.revision)||!Array.isArray(value.allowed_actions)||value.allowed_actions.length>32
    ||value.allowed_actions.some(action=>typeof action!=='string'||!/^[a-z_]{1,60}$/.test(action)))throw Error();
  return {state:value.state,revision:value.revision,allowed_actions:[...value.allowed_actions].sort()};})()`);
const audit = () => page.evaluate("window.__acHlsProof?({...window.__acHlsProof}):null");
const state = () => page.evaluate(`(()=>{const video=${element(VIDEO)};const player=${element(PLAYER)};if(!video||!player)throw Error();const frames=video.getVideoPlaybackQuality?.();return {
  mode:player.dataset.deliveryMode,paused:video.paused,time:video.currentTime,duration:video.duration,ready:video.readyState,seeking:video.seeking,
  rate:video.playbackRate,muted:video.muted,volume:video.volume,width:video.videoWidth,height:video.videoHeight,
  frames:frames?.totalVideoFrames??0,dropped:frames?.droppedVideoFrames??0,
  captions:[...video.querySelectorAll('track')].map(element=>element.track.mode),fullscreen:document.fullscreenElement===player,
  quality:${element(QUALITY)}?.value??null};})()`);
const observePause = async (expected, code) => {
  await page.until(`${element(VIDEO)}?.paused===true&&!${element(VIDEO)}?.seeking`, 30_000);
  await page.delay(350);
  const actual = await state();
  assert(actual.mode === "hls" && actual.paused && Math.abs(actual.time - expected.time) <= 0.75
    && actual.rate === expected.rate && actual.muted === expected.muted && actual.volume === expected.volume
    && same(actual.captions, expected.captions), code);
  return actual;
};
const key = async (name, code) => {
  assert(Date.now() < deadline, "proof_deadline");
  for (const type of ["keyDown", "keyUp"]) await page.send("Input.dispatchKeyEvent", {
    type, key: name, code: name, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code,
    ...(type === "keyDown" && name === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}),
  });
  proof.input.keyboard++;
  await page.delay(80);
};
const mouse = async (expression) => {
  assert(Date.now() < deadline, "proof_deadline");
  await page.until(`Boolean(${expression})&&!(${expression}).disabled`);
  await page.evaluate(`(${expression}).scrollIntoView({behavior:'instant',block:'center',inline:'nearest'})`);
  await page.delay(120);
  const point = await page.evaluate(`(()=>{const target=${expression};const rect=target.getBoundingClientRect();const x=rect.left+rect.width/2,y=rect.top+rect.height/2;const hit=document.elementFromPoint(x,y);
    if(target.disabled||rect.width<=0||rect.height<=0||x<0||y<0||x>=innerWidth||y>=innerHeight||!(hit===target||target.contains(hit)))throw Error();return{x,y}})()`);
  const before = await audit();
  await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
  await page.send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", buttons: 1, clickCount: 1 });
  await page.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", buttons: 0, clickCount: 1 });
  const after = await audit();
  // Native select popups may defer click until selection; trusted mousedown is immediate.
  assert(after && before && after.trustedMouseDowns > before.trustedMouseDowns, "trusted_mouse_input_not_observed");
  proof.input.mouse++;
};
const select = async (selector, value) => {
  const index = await page.evaluate(`(()=>{const select=${element(selector)};if(!select)return -1;return [...select.options].findIndex(option=>option.value===${JSON.stringify(value)})})()`);
  assert(Number.isInteger(index) && index >= 0 && index <= 16, "expected_option_missing");
  await mouse(element(selector));
  assert(await page.evaluate(`document.activeElement===${element(selector)}`), "native_select_not_focused");
  await key("Home", 36);
  for (let step = 0; step < index; step++) await key("ArrowDown", 40);
  await key("Enter", 13);
  await page.until(`${element(selector)}?.value===${JSON.stringify(value)}`);
};
const openSettings = async () => {
  if (!(await page.evaluate(`Boolean(${element(QUALITY)})`))) await mouse(button("Open playback settings"));
  await page.until(`Boolean(${element(QUALITY)})`);
};
const closeSettings = async () => {
  if (await page.evaluate("Boolean(document.querySelector('#momentum-video-settings'))"))
    await mouse("document.querySelector('#momentum-video-settings button[aria-label=\"Close playback settings\"]')");
};
const seekStart = async () => {
  await closeSettings();
  const before = await state();
  assert(before.paused, "seek_reset_requires_paused_player");
  // The local fixture is twelve seconds long. Each rendition trial starts afresh,
  // using the real range control's native Home action, never a currentTime write.
  await mouse(element(POSITION));
  await page.until(`document.activeElement===${element(POSITION)}`);
  await key("Home", 36);
  await page.until(`${element(VIDEO)}?.currentTime<0.15&&!${element(VIDEO)}?.seeking`, 30_000);
  return observePause({ ...before, time: 0 }, "native_seek_start_reset_presentation");
};
const playDecodePause = async (height = null) => {
  const before = await state();
  assert(before.paused && before.time < 0.15 && before.duration - before.time > 3, "unsafe_or_unexpected_playback_position");
  await mouse(button("Play lesson"));
  await page.until(`(()=>{const v=${element(VIDEO)};const q=v?.getVideoPlaybackQuality?.();return Boolean(v&&!v.paused&&v.currentTime>${before.time + 0.8}&&v.videoWidth>0&&q&&q.totalVideoFrames>${before.frames + 3}${height === null ? "" : `&&v.videoHeight===${height}`})})()`, 45_000);
  const playing = await state();
  assert(playing.mode === "hls", "adaptive_mode_lost");
  await mouse(button("Pause lesson"));
  await page.until(`${element(VIDEO)}?.paused===true`);

  return { playing, paused: await state() };
};
const viewport = async (width, height) => {
  await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await page.delay(250);
};
const saveImage = async (name) => {
  await mkdir(output, { recursive: true }); artifactStarted = true;
  const image = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(output, `${name}.png`), Buffer.from(image.data, "base64"), { flag: "wx" });
  proof.captures.push(name);
};
const captureFits = async (name, settings = false) => {
  await page.evaluate(`${element(PLAYER)}.scrollIntoView({behavior:'instant',block:'center',inline:'nearest'})`);
  await page.delay(200);
  const bounds = await page.evaluate(`(()=>{const root=document.documentElement;const selectors=[${JSON.stringify(PLAYER)},'.momentum-video-controls'${settings ? ", '#momentum-video-settings'" : ""}];return{
    client:root.clientWidth,scroll:root.scrollWidth,boxes:selectors.map(selector=>{const e=document.querySelector(selector);if(!e)return null;const r=e.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,client:e.clientWidth,scroll:e.scrollWidth}})};})()`);
  assert(bounds.scroll <= bounds.client + 1 && bounds.boxes.every(box => box && box.left >= -1 && box.right <= bounds.client + 1 && box.scroll <= box.client + 1), "horizontal_overflow");
  const height = await page.evaluate("innerHeight");
  assert(bounds.boxes.every(box => box.top >= -1 && box.bottom <= height + 1), "player_controls_outside_viewport");
  check(name, bounds);
  await saveImage(name);
};

try {
  // Open a harmless holding route first: instrumentation precedes the activity mount.
  page = await localPage({ pathname: "/__ac-adaptive-video-proof", newTab: true });
  await page.send("Page.navigate", { url: `${ORIGIN}/__ac-adaptive-video-proof` });
  await page.until(`location.origin===${JSON.stringify(ORIGIN)}&&location.pathname==='/__ac-adaptive-video-proof'&&document.readyState==='complete'`, 45_000);
  await page.evaluate(guardSource);
  const registration = await page.send("Page.addScriptToEvaluateOnNewDocument", { source: guardSource });
  scriptId = registration.identifier;
  stage = "synthetic-identity";
  await identityGuard(); identityVerified = true;
  check("synthetic learner and exact academy verified");
  proof.allowed_actions_before = await activitySnapshot();
  assert(!proof.allowed_actions_before.allowed_actions.includes("complete_video"), "tracked_playback_refused");
  check("baseline has no complete_video action");
  stage = "actual-activity-load";
  const previousDocument = await page.evaluate("performance.timeOrigin");
  await page.send("Page.navigate", { url: `${ORIGIN}/activity/${ACTIVITY}` });
  await page.until(`performance.timeOrigin!==${previousDocument}&&location.origin===${JSON.stringify(ORIGIN)}&&location.pathname===${JSON.stringify(`/activity/${ACTIVITY}`)}&&document.readyState==='complete'&&Boolean(window.__acHlsProof)`, 60_000);
  await identityGuard();
  await viewport(1440, 1000);
  await page.send("Page.bringToFront");
  await page.until(`Boolean(${element(PLAYER)})&&${element(PLAYER)}.dataset.deliveryMode==='hls'&&${element(VIDEO)}?.readyState>=2`, 45_000);
  readonlyVerified = true;
  const initial = await state();
  assert(initial.paused && Number.isFinite(initial.duration) && initial.duration >= 11 && initial.duration <= 13, "expected_paused_twelve_second_fixture_unavailable");
  check("actual HLS read-only mount", initial);
  stage = "central-start-and-decode";
  await mouse(button("Start video"));
  await page.until(`(()=>{const v=${element(VIDEO)};return v&&!v.paused&&v.currentTime>0.8&&v.videoWidth>0&&v.getVideoPlaybackQuality().totalVideoFrames>3})()`, 45_000);
  check("central start decoded actual frames", await state());
  await mouse(button(surfaceProof ? "Pause video" : "Pause lesson"));
  await page.until(`${element(VIDEO)}?.paused===true`);
  if (surfaceProof) {
    stage = "picture-native-keyboard";
    // The native picture click left focus on the same real button.
    assert(await page.evaluate("document.activeElement?.classList.contains('momentum-video-player__surface')"), "picture_not_focused");
    await key(" ", 32);
    await page.until(`${element(VIDEO)}?.paused===false`);
    await key(" ", 32);
    await page.until(`${element(VIDEO)}?.paused===true`);
    check("picture mouse and native Space play/pause", await state());
    stage = "picture-settings-dismiss";
    await openSettings();
    await mouse("document.querySelector('.momentum-video-player__surface')");
    await page.until("!document.querySelector('#momentum-video-settings')");
    assert((await state()).paused, "settings_dismiss_toggled_playback");
    check("picture dismisses Settings without playback click-through");
    stage = "picture-touch";
    await viewport(390, 844);
    await page.evaluate(`${element(PLAYER)}.scrollIntoView({behavior:'instant',block:'center'})`);
    await page.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
    try {
      const point = await page.evaluate("(()=>{const e=document.querySelector('.momentum-video-player__surface');const r=e.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/3;const hit=document.elementFromPoint(x,y);if(!(hit===e||e.contains(hit)))throw Error();return{x,y}})()");
      for (const paused of [false, true]) {
        await page.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point] });
        await page.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
        await page.until(`${element(VIDEO)}?.paused===${paused}`);
      }
      check("picture native emulated touch play/pause", await state());
    } finally {
      await page.send("Emulation.setTouchEmulationEnabled", { enabled: false });
    }
    await viewport(1440, 1000);
  }
  stage = "nondefault-presentation-controls";
  await openSettings();
  await select(RATE, "1.5");
  await page.until(`${element(VIDEO)}?.playbackRate===1.5`);
  if (await page.evaluate(`Boolean(${settingsButton("Captions on")})`)) await mouse(settingsButton("Captions on"));
  await closeSettings();
  if (!(await state()).muted) await mouse(button("Mute lesson"));
  await page.until(`[...${element(VIDEO)}.querySelectorAll('track')].length>0&&[...${element(VIDEO)}.querySelectorAll('track')].every(element=>element.track.mode!=='showing')`);
  check("native rate, mute and captions-off controls", await state());
  if (renewalProof) {
    stage = "real-time-delivery-renewal";
    const before = await state();
    const delivery = await audit();
    assert(delivery.mediaGrants === 1 && delivery.firstMediaExpiry > Date.now() && delivery.firstMediaExpiry - Date.now() <= 300_000, "initial_real_grant_window_unavailable");
    await saveImage("renewal-before-paused");
    process.stdout.write("Observing the real local grant deadline; no clock change, synthetic token or harness refresh.\n");
    // Only observe the owned player. Its normal activity read must renew access.
    // No API read from this harness may mint the successor during this interval.
    while (Date.now() <= delivery.firstMediaExpiry + 1500) {
      assert(Date.now() < deadline, "renewal_deadline");
      await page.delay(1000);
    }
    const rotated = await audit();
    assert(rotated.mediaGrants === 2, "player_did_not_rotate_exactly_once");
    const retained = await observePause(before, "renewal_reset_paused_presentation");
    const expiredStatus = await page.evaluate("window.__acHlsProofExpired()");
    assert([401, 403, 410].includes(expiredStatus), "expired_original_manifest_not_denied");
    check("real grant rotation retains paused position and controls beyond old expiry", { before, after: retained, grants: rotated.mediaGrants, expired_original_status: expiredStatus });
    await saveImage("renewal-after-old-expiry");
    await seekStart();
    const renewedDecode = await playDecodePause();
    check("fresh grant decodes actual frames after predecessor expiry", renewedDecode.playing);
  }
  for (const height of [360, 1080, 2160, null]) {
    stage = height === null ? "quality-auto" : `quality-${height}`;
    await seekStart();
    await openSettings();
    const value = height === null ? "auto" : await page.evaluate(`(()=>{const matches=[...${element(QUALITY)}.options].filter(option=>option.textContent.trim()===${JSON.stringify(`${height}p`)});return matches.length===1?matches[0].value:null})()`);
    assert(value === "auto" || /^hls-\d{1,2}$/.test(value ?? ""), "required_quality_missing_or_ambiguous");
    const before = await state();
    await select(QUALITY, value);
    const unchanged = await observePause(before, "quality_changed_paused_presentation");
    await closeSettings();
    const decoded = await playDecodePause(height);
    assert(decoded.paused.rate === before.rate && decoded.paused.muted === before.muted
      && decoded.paused.volume === before.volume && same(decoded.paused.captions, before.captions), "quality_reset_presentation_controls");
    check(stage, { selected: height ?? "auto", paused_switch: unchanged, decoded: decoded.playing });
    await openSettings();
    assert(await page.evaluate(`${element(QUALITY)}.value===${JSON.stringify(value)}`), "quality_selection_not_retained");
    await captureFits(`${stage}-desktop`, true);
    await closeSettings();
  }
  stage = "native-seek";
  const beforeSeek = await seekStart();
  const expectedForward = Math.min(beforeSeek.duration, beforeSeek.time + 10);
  await openSettings();
  await mouse(settingsButton("Forward 10s"));
  await page.until(`Math.abs(${element(VIDEO)}.currentTime-${expectedForward})<0.75&&!${element(VIDEO)}.seeking`);
  const forward = await state();
  const expectedBack = Math.max(0, forward.time - 10);
  await mouse(settingsButton("Back 10s"));
  await closeSettings();
  const restored = await observePause({ ...beforeSeek, time: expectedBack }, "seek_back_did_not_restore_position");
  check("native forward/back seek", { before: beforeSeek.time, forward: forward.time, restored: restored.time });
  stage = "native-fullscreen";
  await mouse(button("Enter fullscreen"));
  await page.until(`document.fullscreenElement===${element(PLAYER)}`);
  check("fullscreen player target", await state());
  await saveImage("fullscreen-paused");
  await mouse(button("Exit fullscreen"));
  await page.until("document.fullscreenElement===null");
  await observePause(restored, "fullscreen_reset_presentation");
  stage = "restore-presentation";
  await openSettings();
  await select(RATE, String(initial.rate));
  if (initial.captions.some(mode => mode === "showing")) {
    await mouse(settingsButton("Captions off"));
    await page.until(`[...${element(VIDEO)}.querySelectorAll('track')].some(element=>element.track.mode==='showing')`);
  }
  await closeSettings();
  if ((await state()).muted !== initial.muted) await mouse(button(initial.muted ? "Mute lesson" : "Unmute lesson"));
  for (const [width, height] of [[390, 844], [320, 740], [768, 1024], [1440, 1000]]) {
    stage = `viewport-${width}`;
    await viewport(width, height);
    await captureFits(`player-${width}`);
    await openSettings();
    await captureFits(`settings-${width}`, true);
    await closeSettings();
  }
  stage = "final-readonly-audit";
  await identityGuard();
  proof.allowed_actions_after = await activitySnapshot();
  assert(same(proof.allowed_actions_before, proof.allowed_actions_after), "activity_state_changed");
  const observed = await audit();
  assert(observed && observed.blockedWrites === 0 && observed.blockedExternal === 0 && page.external() === 0, "unexpected_network_activity");
  assert(observed.trustedClicks > 0 && observed.trustedKeys > 0 && observed.trustedChanges > 0, "native_input_not_observed");
  const final = await state();
  assert(final.paused && final.mode === "hls" && final.rate === initial.rate && final.muted === initial.muted && final.volume === initial.volume && same(final.captions, initial.captions), "paused_handoff_not_preserved");
  check("unchanged canonical activity and no mutation attempts", observed);
  check("paused HLS handoff with original presentation settings", final);
  proof.status = "passed";
} catch (error) {
  proof.status = "failed";
  proof.failure = { stage, code: error instanceof ProofFailure ? error.code : "browser_or_read_command_failed" };
  if (page && identityVerified) {
    proof.partial_audit = await audit().catch(() => null);
    if (readonlyVerified) proof.partial_video = await state().catch(() => null);
    await saveImage("failure-current-viewport").catch(() => {});
  }
  process.exitCode = 1;
} finally {
  if (page) {
    proof.blocked_external_requests = page.external();
    if (proof.status === "passed") {
      await page.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
      if (scriptId) await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: scriptId }).catch(() => {});
      await page.evaluate("window.__acHlsProofCleanup?.()").catch(() => {});
      if (surfaceProof) {
        await page.send("Page.close").catch(() => {});
        const remaining = await fetch("http://127.0.0.1:9327/json/list", { signal: AbortSignal.timeout(5000) }).then(r => r.json()).catch(() => null);
        proof.owned_tab_closed = Boolean(page.createdTargetId && Array.isArray(remaining) && !remaining.some(target => target.id === page.createdTargetId));
        if (!proof.owned_tab_closed) {
          proof.status = "failed";
          proof.failure = { stage: "owned-tab-cleanup", code: "owned_tab_close_unconfirmed" };
          process.exitCode = 1;
        }
      }
      // Ordinary HLS proof keeps its owned paused tab for user inspection.
      // Focused surface proof closes its exact owned target; no tab-list inference.
      await page.close().catch(() => {});
    } else {
      // Closing ONLY the newly created tab also stops playback if a native control failed.
      await page.send("Page.close").catch(() => {});
      await page.close().catch(() => {});
    }
  }
  if (proof.checks.length || artifactStarted) {
    await mkdir(output, { recursive: true });
    await writeFile(path.join(output, "proof.json"), JSON.stringify(proof, null, 2) + "\n", { flag: "wx" });
    process.stdout.write(JSON.stringify({ status: proof.status, stage, completed_checks: proof.checks.length, evidence_directory: output }) + "\n");
  } else {
    process.stderr.write("Local HLS acceptance not run to an evidence-producing state. Browser connection or synthetic identity preflight unavailable. No credentials were read.\n");
  }
}
