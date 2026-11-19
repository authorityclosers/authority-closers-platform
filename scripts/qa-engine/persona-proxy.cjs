// Persona sign-in proxy for the QA robot (dev only), rebuilt 8 Nov 2026 after ac rebooted and /tmp was emptied.
// It is the proxy half of the 31 Oct persona driver (the control API on :9777 that drove Chromium is not rebuilt):
// a pass-through on 127.0.0.1:3098 in front of dev-live (web :3026, API :8101 with the dev Host) that also signs a
// fictional sandbox person in at /__as/<persona>?next=/path (a 302 with the session cookie). The password of each
// person comes from the environment (ac-infisical-run injects dev /sandbox-logins at start) and is never printed or
// returned. There is no owner alias: the owner's own session is not the robot's to use.
const net = require("net");
const http = require("http");

const SITE = "salesxray-dev.authorityclosers.com";
const PROXY_PORT = 3098;
const WEB_PORT = 3026;
const API_PORT = 8101;
const BASE = `http://localhost:${PROXY_PORT}`;

const PERSONAS = {
  priya: ["admin+ac.priya@authorityclosers.com", "SANDBOX_LOGIN_AC_PRIYA"],
  rohan: ["admin+ac.rohan@authorityclosers.com", "SANDBOX_LOGIN_AC_ROHAN"],
  sneha: ["admin+ac.sneha@authorityclosers.com", "SANDBOX_LOGIN_AC_SNEHA"],
  aditya: ["admin+ac.aditya@authorityclosers.com", "SANDBOX_LOGIN_AC_ADITYA"],
  farah: ["admin+ac.farah@authorityclosers.com", "SANDBOX_LOGIN_AC_FARAH"],
  karan: ["admin+cy.karan@authorityclosers.com", "SANDBOX_LOGIN_CY_KARAN"],
  neha: ["admin+cy.neha@authorityclosers.com", "SANDBOX_LOGIN_CY_NEHA"],
  imran: ["admin+cy.imran@authorityclosers.com", "SANDBOX_LOGIN_CY_IMRAN"],
  pooja: ["admin+cy.pooja@authorityclosers.com", "SANDBOX_LOGIN_CY_POOJA"],
  vikas: ["admin+cy.vikas@authorityclosers.com", "SANDBOX_LOGIN_CY_VIKAS"],
  // the owner-view person: a fictional Admin of the AC Sales Sandbox (the orchestrator, 8 Nov 2026); sees what an Owner sees
  anjali: ["admin+ac.anjali@authorityclosers.com", "SANDBOX_LOGIN_AC_ANJALI"],
};

function upstreamRequest(opts, body) {
  return new Promise((resolve, reject) => {
    const r = http.request(opts, (answer) => {
      const chunks = [];
      answer.on("data", (c) => chunks.push(c));
      answer.on("end", () => resolve({ status: answer.statusCode, headers: answer.headers, body: Buffer.concat(chunks) }));
    });
    r.on("error", reject);
    if (body) r.write(body);
    r.end();
  });
}

async function signIn(persona) {
  const entry = PERSONAS[persona];
  if (!entry) return { status: 404, cookies: [] };
  const password = process.env[entry[1]];
  if (!password) return { status: 500, cookies: [] };
  const body = JSON.stringify({ email: entry[0], password });
  const r = await upstreamRequest(
    {
      host: "127.0.0.1",
      port: API_PORT,
      method: "POST",
      path: "/v1/auth/password/login",
      headers: {
        host: SITE,
        origin: `https://${SITE}`,
        referer: `https://${SITE}/login`,
        accept: "application/json",
        "content-type": "application/json",
        "content-length": Buffer.byteLength(body),
      },
    },
    body,
  );
  return { status: r.status, cookies: r.headers["set-cookie"] || [] };
}

const proxy = http.createServer(async (req, res) => {
  try {
    if (req.url.startsWith("/__as/")) {
      const url = new URL(req.url, BASE);
      const persona = url.pathname.slice("/__as/".length);
      const next = url.searchParams.get("next") || "/";
      const out = await signIn(persona);
      if (out.status >= 400 || out.cookies.length === 0) {
        res.writeHead(502, { "content-type": "text/plain" });
        res.end(`sign-in as ${persona} failed (HTTP ${out.status})`);
        return;
      }
      res.writeHead(302, { location: next, "set-cookie": out.cookies });
      res.end();
      return;
    }
    const api = req.url.startsWith("/v1/");
    const headers = { ...req.headers };
    if (api) {
      headers.host = SITE;
      if (headers.origin) headers.origin = `https://${SITE}`;
      if (headers.referer) headers.referer = `https://${SITE}/`;
    }
    const upstream = http.request(
      { host: "127.0.0.1", port: api ? API_PORT : WEB_PORT, method: req.method, path: req.url, headers },
      (answer) => {
        res.writeHead(answer.statusCode, answer.headers);
        answer.pipe(res);
      },
    );
    upstream.on("error", () => {
      if (!res.headersSent) res.writeHead(502);
      res.end();
    });
    req.pipe(upstream);
  } catch (error) {
    if (!res.headersSent) res.writeHead(500);
    res.end();
  }
});
proxy.on("upgrade", (req, socket, head) => {
  const upstream = net.connect(WEB_PORT, "127.0.0.1", () => {
    const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
    for (let i = 0; i < req.rawHeaders.length; i += 2) lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
    upstream.write(lines.join("\r\n") + "\r\n\r\n");
    if (head && head.length) upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
});
proxy.on("error", (error) => {
  console.error(`proxy error: ${error.code || error.message}`);
  process.exit(1);
});
proxy.listen(PROXY_PORT, "127.0.0.1", () => console.log(`persona proxy on ${PROXY_PORT}`));
