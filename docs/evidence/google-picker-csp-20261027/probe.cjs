// Open Google's real Picker (fictional key and token) on a page served with a Sales X-Ray
// edge CSP read from a Caddy file; report what the page loaded, framed and was refused.
// Usage: LD_LIBRARY_PATH=<libs> node picker_csp_probe.cjs <env.caddy> <label>
const fs = require("fs");
const http = require("http");
const path = require("path");
const APP =
  "/home/acdev/src/dev-live/authority-closers-platform/apps/sales-xray-web";
const { chromium } = require(require.resolve("playwright", { paths: [APP] }));

const [caddyFile, label] = process.argv.slice(2);
const env = path.basename(caddyFile, ".caddy");
const source = fs.readFileSync(caddyFile, "utf8");
const block = source.split(`handle @${env}_sales_xray {`)[1].split("\n\t}")[0];
const policy = /header Content-Security-Policy "([^"\n]+)"/.exec(block)[1];

const html = `<!doctype html><meta charset="utf-8"><title>Picker CSP probe</title><body>
<script>
window.events = [];
addEventListener("securitypolicyviolation", (e) =>
  window.events.push({ violation: e.effectiveDirective, blocked: e.blockedURI.split("?")[0] }));
function start() {
  window.events.push({ api: "loaded" });
  gapi.load("picker", { callback: () => {
    window.events.push({ picker: "module loaded" });
    const view = new google.picker.DocsView(google.picker.ViewId.SPREADSHEETS);
    const picker = new google.picker.PickerBuilder().addView(view)
      .setOAuthToken("ya29.fictional-token").setDeveloperKey("fictional-browser-key")
      .setAppId("123456789012").setOrigin(location.origin)
      .setCallback((data) => window.events.push({ callback: data && data.action })).build();
    picker.setVisible(true);
    window.events.push({ picker: "visible" });
  }, onerror: () => window.events.push({ picker: "module error" }) });
}
</script>
<script src="https://apis.google.com/js/api.js" onload="start()"
  onerror="window.events.push({ api: 'refused' })"></script>`;

const server = http.createServer((req, res) => {
  if (req.url !== "/") {
    res.writeHead(404);
    res.end();
    return;
  }
  res.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": policy,
  });
  res.end(html);
});

const strip = (url) => {
  try {
    const u = new URL(url);
    return u.origin + u.pathname;
  } catch {
    return url;
  }
};

server.listen(0, "127.0.0.1", async () => {
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const mainRequests = new Map();
  const frameOrigins = new Set();
  const failed = [];
  page.on("request", (request) => {
    if (request.frame() === page.mainFrame()) {
      const key = `${request.resourceType()} ${new URL(request.url()).origin}`;
      mainRequests.set(key, (mainRequests.get(key) || 0) + 1);
    }
  });
  page.on(
    "frameattached",
    (frame) => frame.url() && frameOrigins.add(frame.url()),
  );
  page.on("framenavigated", (frame) => {
    if (frame !== page.mainFrame()) {
      try {
        frameOrigins.add(new URL(frame.url()).origin);
      } catch {}
    }
  });
  page.on("requestfailed", (request) => {
    if (request.frame() === page.mainFrame())
      failed.push(`${strip(request.url())} ${request.failure()?.errorText}`);
  });
  await page.goto(origin, { waitUntil: "load" });
  await page.waitForTimeout(12000);
  const events = await page.evaluate(() => window.events);
  const frames = await page.evaluate(() =>
    [...document.querySelectorAll("iframe")].map((f) => {
      try {
        return new URL(f.src).origin;
      } catch {
        return f.src;
      }
    }),
  );
  console.log(
    JSON.stringify(
      {
        label,
        policy,
        events,
        iframes_in_page: frames,
        frame_origins_loaded: [...frameOrigins].filter((o) =>
          o.startsWith("http"),
        ),
        page_requests: Object.fromEntries(mainRequests),
        page_requests_failed: failed,
      },
      null,
      2,
    ),
  );
  await browser.close();
  server.close();
});
