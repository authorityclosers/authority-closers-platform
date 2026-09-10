// Page-target CDP avoids browser-wide attachment to Chrome's browser_ui targets.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const targets = await fetch("http://127.0.0.1:9327/json/list").then((r) => r.json());
const target = targets.find((t) => t.type === "page" && new URL(t.url).hostname === "learner.localhost");
if (!target) throw new Error("Authenticated local learner tab unavailable");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
let nextId = 0;
const pending = new Map();
socket.addEventListener("message", ({ data }) => {
  const result = JSON.parse(data);
  if (pending.has(result.id)) {
    const { resolve, reject, timer } = pending.get(result.id);
    pending.delete(result.id); clearTimeout(timer);
    if (result.error) reject(new Error("Local page command failed")); else resolve(result.result);
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error("Local page command timed out")); }, 15000);
  pending.set(id, { resolve, reject, timer });
  socket.send(JSON.stringify({ id, method, params }));
});
const output = path.resolve("docs/evidence/screenshots/arcade-review-20260908");
await mkdir(output, { recursive: true });
try {
  await send("Page.enable");
  for (const [label, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    for (const [surface, suffix] of [["hub", "/practice"], ["drill", "/practice?set=next-move"]]) {
      await send("Page.navigate", { url: "http://learner.localhost:3100" + suffix });
      await new Promise((resolve) => setTimeout(resolve, 5000));
      const screenshot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      await writeFile(path.join(output, `${surface}-${label}.png`), Buffer.from(screenshot.data, "base64"));
      process.stdout.write(`${surface}-${label}.png saved\n`);
    }
  }
  await send("Emulation.clearDeviceMetricsOverride");
} finally { socket.close(); }
