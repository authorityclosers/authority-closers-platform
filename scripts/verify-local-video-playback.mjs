// Actual visible Chrome playback proof; page-level CDP does not read session values.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const origin = "http://learner.localhost:3100";
const activity = "2dbf0371-8456-5610-bb2f-629968a8e22d";
const targets = await fetch("http://127.0.0.1:9327/json/list").then((r) => r.json());
const target = targets.find((item) => item.type === "page" && new URL(item.url).hostname === "learner.localhost");
if (!target) throw new Error("Signed-in local learner tab unavailable");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let nextId = 0;
let blockedExternal = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error("Local page command timed out")); }, 15000);
  pending.set(id, { resolve, reject, timer });
  socket.send(JSON.stringify({ id, method, params }));
});
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data);
  if (message.method === "Fetch.requestPaused") {
    const { requestId, request } = message.params;
    const allowed = ["learner.localhost", "admin.localhost", "127.0.0.1"].includes(new URL(request.url).hostname);
    if (!allowed) blockedExternal += 1;
    void send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest", {
      requestId, ...(allowed ? {} : { errorReason: "BlockedByClient" }),
    }).catch(() => {});
  }
  if (pending.has(message.id)) {
    const { resolve, reject, timer } = pending.get(message.id);
    pending.delete(message.id); clearTimeout(timer);
    if (message.error) reject(new Error("Local page command failed")); else resolve(message.result);
  }
});
const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error("Local page evaluation failed");
  return result.result.value;
};
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const until = async (expression, description, timeout = 30000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return;
    await delay(250);
  }
  throw new Error(description);
};
const button = (label) => `[...document.querySelectorAll('button')].find(e => e.getAttribute('aria-label') === ${JSON.stringify(label)} || e.textContent.trim() === ${JSON.stringify(label)})`;
const clickExpression = async (expression) => {
  const point = await evaluate(`(() => {const e = ${expression}; if(!e || e.disabled) return null; e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  if (!point) throw new Error("Expected local playback control unavailable");
  await send("Runtime.evaluate", { expression: `${expression}.click()`, userGesture: true });
};
const key = async (name, code) => {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code: name, windowsVirtualKeyCode: code });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code: name, windowsVirtualKeyCode: code });
};
try {
  await send("Page.enable");
  process.stdout.write("Page connection ready\n");
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  await send("Page.navigate", { url: `${origin}/activity/${activity}` });
  process.stdout.write("Film activity opened\n");
  await send("Page.bringToFront");
  process.stdout.write("Film tab brought forward\n");
  await until(`Boolean(${button("Start video")}) && !${button("Start video")}?.disabled`, "Central Start video control unavailable");
  process.stdout.write("Central Start video ready\n");
  await clickExpression(button("Start video"));
  process.stdout.write("Central Start video clicked\n");
  await until("document.querySelector('video')?.currentTime > 1.2", "Actual playback did not advance");
  const moving = await evaluate("(() => {const v=document.querySelector('video'); return {time:v.currentTime,width:v.videoWidth,height:v.videoHeight,frames:v.getVideoPlaybackQuality().totalVideoFrames,paused:v.paused};})()");
  if (!moving.width || !moving.height || moving.frames < 2 || moving.paused) throw new Error("Decoded playback not proven");
  process.stdout.write("Decoded frames and advancing playback verified\n");
  await clickExpression(button("Pause lesson"));
  await until("document.querySelector('video').paused", "Playback did not pause");
  await clickExpression(button("Skip forward 10 seconds (L)"));
  await until("document.querySelector('video').currentTime > 10", "Seek forward failed");
  const seekTime = await evaluate("document.querySelector('video').currentTime");
  await clickExpression(button("Skip back 10 seconds (J)"));
  await until("document.querySelector('video').currentTime < 5", "Seek backward failed");
  const rateControlPresent = await evaluate("Boolean(document.querySelector('[aria-label=\"Playback speed\"]'))");
  if (rateControlPresent) {
    await send("Runtime.evaluate", { expression: "(()=>{const e=document.querySelector('[aria-label=\"Playback speed\"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,'1.5');e.dispatchEvent(new Event('change',{bubbles:true}));})()", userGesture: true });
    await until("document.querySelector('video').playbackRate === 1.5", "Playback speed control failed");
    await send("Runtime.evaluate", { expression: "(()=>{const e=document.querySelector('[aria-label=\"Playback speed\"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,'1');e.dispatchEvent(new Event('change',{bubbles:true}));})()", userGesture: true });
    await until("document.querySelector('video').playbackRate === 1", "Playback speed restoration failed");
  }
  if (await evaluate(`Boolean(${button("Show captions")})`)) await clickExpression(button("Show captions"));
  await until("[...document.querySelector('video').textTracks].some(t => t.mode === 'showing')", "Caption selection failed");
  await clickExpression(button("Enter fullscreen"));
  await until("Boolean(document.fullscreenElement)", "Fullscreen entry failed");
  await clickExpression(button("Exit fullscreen"));
  await until("!document.fullscreenElement", "Fullscreen exit failed");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await evaluate("window.scrollTo(0,0)");
  await delay(500);
  const output = path.resolve("docs/evidence/screenshots/local-video-playback-20260908");
  await mkdir(output, { recursive: true });
  const screenshot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(path.join(output, "02-paused-decoded-frame-with-rate-desktop.png"), Buffer.from(screenshot.data, "base64"));
  await send("Emulation.clearDeviceMetricsOverride");
  if (!await evaluate("document.querySelector('video').paused")) throw new Error("Expected paused handoff");
  process.stdout.write(JSON.stringify({ status: "passed", actual_decoded_playback: moving, seek_time: seekTime, rate_control_present: rateControlPresent, captions_fullscreen: true, left_paused: true, blocked_external_requests: blockedExternal, interaction: "CDP user-gesture UI button invocation" }) + "\n");
} catch (error) {
  // Error messages above are fixed strings; do not print runtime URLs or browser diagnostics.
  process.stderr.write(`Local video proof incomplete: ${error.message}\n`);
  const state = await evaluate("({controls:[...document.querySelectorAll('button,select,input')].map(e=>({label:e.getAttribute('aria-label')||e.textContent.trim(),tag:e.tagName})),video:(()=>{const v=document.querySelector('video');return v?{time:v.currentTime,paused:v.paused,width:v.videoWidth,height:v.videoHeight}:null})()})").catch(() => null);
  if (state) process.stdout.write(JSON.stringify(state) + "\n");
  process.exitCode = 1;
} finally {
  await send("Fetch.disable").catch(() => {});
  socket.close();
}
