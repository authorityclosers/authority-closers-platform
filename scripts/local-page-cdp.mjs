// Local browser acceptance utilities. Never read cookies, token URLs or credentials.
export async function localPage({ pathname, newTab = false, surface = "learner" } = {}) {
  if (!["learner", "admin", "coach"].includes(surface)) throw new Error("Unknown local surface");
  const origin = {admin: "http://admin.localhost:3101", learner: "http://learner.localhost:3100", coach: "http://coach.localhost:3102"}[surface];
  const target = newTab
    ? await fetch(`http://127.0.0.1:9327/json/new?${origin}${pathname ?? "/home"}`, { method: "PUT" }).then((r) => r.json())
    : (await fetch("http://127.0.0.1:9327/json/list").then((r) => r.json())).find((t) => t.type === "page" && new URL(t.url).origin === origin);
  if (!target) throw new Error("Local learner tab unavailable");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let id = 0;
  let blockedExternal = 0;
  const pending = new Map();
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const next = ++id;
    const timer = setTimeout(() => { pending.delete(next); reject(new Error("Local browser command timed out")); }, 15000);
    pending.set(next, { resolve, reject, timer }); socket.send(JSON.stringify({ id: next, method, params }));
  });
  socket.addEventListener("message", ({ data }) => {
    const result = JSON.parse(data);
    if (result.method === "Fetch.requestPaused") {
      const { requestId, request } = result.params;
      const allowed = ["learner.localhost", "admin.localhost", "coach.localhost", "127.0.0.1"].includes(new URL(request.url).hostname);
      if (!allowed) blockedExternal += 1;
      void send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest", { requestId, ...(allowed ? {} : { errorReason: "BlockedByClient" }) }).catch(() => {});
    }
    if (!pending.has(result.id)) return;
    const { resolve, reject, timer } = pending.get(result.id); pending.delete(result.id); clearTimeout(timer);
    if (result.error) reject(new Error("Local browser command refused")); else resolve(result.result);
  });
  const evaluate = async (expression, gesture = false) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true, userGesture: gesture });
    if (result.exceptionDetails) throw new Error("Local browser evaluation unavailable");
    return result.result.value;
  };
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const until = async (expression, timeout = 30000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { try { if (await evaluate(expression)) return; } catch { /* Navigation may replace the execution context. */ } await delay(200); }
    throw new Error("Expected local UI state not reached");
  };
  const button = (label) => `[...document.querySelectorAll('button')].find(e => e.getAttribute('aria-label') === ${JSON.stringify(label)} || e.textContent.trim() === ${JSON.stringify(label)})`;
  const click = async (label) => {
    await until(`Boolean(${button(label)}) && !${button(label)}.disabled`);
    await evaluate(`${button(label)}.click()`, true);
  };
  await send("Page.enable"); await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  if (!newTab && pathname) await send("Page.navigate", { url: origin + pathname });
  await send("Page.bringToFront");
  return { send, evaluate, until, button, click, delay,
    createdTargetId: newTab ? target.id : null,
    external: () => blockedExternal,
    close: async () => { await send("Fetch.disable").catch(() => {}); socket.close(); } };
}
