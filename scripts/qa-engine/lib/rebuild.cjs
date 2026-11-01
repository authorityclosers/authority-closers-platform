// Is dev rebuilding right now? The Next dev overlay says it is compiling or has a build error, "compiling..." is in the
// page, or three or more /_next 4xx/5xx or failed requests came in the last minute. A check that fails during a rebuild
// says nothing about the app. Only the overlay's words are read, never its style sheets.
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function rebuilding(tab) {
  if (!require("./guard.cjs").snapshot().devOk) return true; // the dev probe says the pages do not compile
  const recent = ((tab.log && tab.log.nextErrors) || []).filter((t) => Date.now() - t < 60000).length;
  if (recent >= 3) return true;
  return tab.page
    .evaluate(() => {
      const portal = document.querySelector("nextjs-portal");
      const shadow = portal && portal.shadowRoot ? portal.shadowRoot : null;
      const words = shadow
        ? [...shadow.children]
            .filter((e) => e.tagName !== "STYLE")
            .map((e) => e.textContent || "")
            .join(" ")
            .replace(/\s+/g, " ")
        : "";
      if (/compiling|rebuilding|full reload|build error|failed to compile|module not found|syntax error/i.test(words)) return true;
      const text = ((document.body && document.body.innerText) || "").slice(0, 4000);
      return /compiling\.\.\.|Fast Refresh had to perform a full reload/i.test(text);
    })
    .catch(() => false);
}

async function waitOutRebuild(tab, maxMs = 150000) {
  const start = Date.now();
  while (Date.now() - start < maxMs && (await rebuilding(tab))) await sleep(10000);
  await sleep(2000);
}

module.exports = { rebuilding, waitOutRebuild };
