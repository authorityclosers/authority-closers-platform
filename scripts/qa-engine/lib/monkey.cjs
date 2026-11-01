// gremlins.js monkey runs on dev pages: a horde of random clicks, touches, typing, scrolling and form filling,
// then what broke. Read-only by construction: every write to the API is blocked while it runs, tel:/mailto:/
// WhatsApp and outside links are not clickable, and destructive words are never tapped. Reports console and
// script errors, unhandled rejections, a blank page and layout breaks, with the seed so a run can be replayed.
const path = require("path");
const cfg = require("./config.cjs");
const { go, settle } = require("./session.cjs");
const { probe } = require("./probe.cjs");

const DANGER = /log ?out|sign ?out|delete|remove|erase|reset|close account|import|send|submit|call|dial|whatsapp|upload|pay|buy|upgrade|checkout|revoke|disconnect|unlink|archive|invite|transfer/i;

async function installReadOnly(tab) {
  await tab.context.route("**/v1/**", (route) => {
    const method = route.request().method();
    if (method === "GET" || method === "HEAD" || method === "OPTIONS") return route.continue();
    return route.abort("blockedbyclient");
  });
}

async function unleash(tab, route, { seed, count = 300, delay = 40 }) {
  const page = tab.page;
  const mark = tab.mark();
  await page.addScriptTag({ path: require.resolve("gremlins.js/dist/gremlins.min.js") });
  const outcome = await page.evaluate(
    async ({ seed, count, delay, danger }) => {
      const dangerous = new RegExp(danger, "i");
      const safe = (el) => {
        if (!el || !el.closest) return false;
        const link = el.closest("a[href]");
        if (link) {
          const href = link.getAttribute("href") || "";
          if (/^(tel:|mailto:|sms:|whatsapp:|intent:)|wa\.me|^https?:\/\//i.test(href) && !href.startsWith(location.origin)) return false;
          if (link.target === "_blank") return false;
        }
        const control = el.closest("button,[role=button],a,label,input,[role=menuitem]") || el;
        const text = `${control.getAttribute("aria-label") || ""} ${control.textContent || ""}`.slice(0, 120);
        return !dangerous.test(text);
      };
      window.confirm = () => false;
      window.alert = () => {};
      window.open = () => null;
      const g = window.gremlins;
      const species = [
        g.species.clicker({ clickTypes: ["click"], canClick: safe, showAction: () => {} }),
        g.species.toucher({ touchTypes: ["tap", "gesture"], canTouch: safe, showAction: () => {} }),
        g.species.formFiller({ canFillElement: (el) => !/password|file/i.test(el.type || ""), showAction: () => {} }),
        g.species.scroller({ showAction: () => {} }),
        g.species.typer({ showAction: () => {} }),
      ];
      const horde = g.createHorde({
        species,
        mogwais: [],
        strategies: [g.strategies.distribution({ distribution: [0.45, 0.2, 0.15, 0.1, 0.1], delay })],
        randomizer: new g.Chance(seed),
      });
      await Promise.race([horde.unleash({ nb: count }), new Promise((resolve) => setTimeout(resolve, 45000))]);
      return "done";
    },
    { seed, count, delay, danger: DANGER.source },
  ).catch((error) => `failed: ${String(error).split("\n")[0].slice(0, 120)}`);
  await settle(tab, 6000);
  const expected = [/Failed to fetch|NetworkError|Load failed|AbortError/i];
  const found = await probe(tab, route, { mark, skipAxe: true, expectedErrors: expected, knownHttp: [/^(401|403|404) /] });
  const replay = `seed ${seed}, ${count} gremlins, ${delay} ms apart`;
  return {
    outcome,
    findings: found.map((f) => ({
      ...f,
      rule: `monkey:${f.rule}`,
      detail: `${f.detail} Replay: ${replay}.`,
    })),
    replay,
  };
}

async function releaseReadOnly(tab) {
  await tab.context.unroute("**/v1/**").catch(() => null);
}

// Runs the monkey on one route. The caller's tab is read-only afterwards, so give it a tab of its own.
async function monkeyRoute(tab, route, seed) {
  await installReadOnly(tab);
  const opened = await go(tab, route, { wait: 25000 });
  if (!opened.ok) return { outcome: "did not open", findings: [{ rule: "monkey:page-load", selector: "", severity: "MAJOR", summary: "The page did not open for the monkey run", detail: opened.error, route }] };
  return unleash(tab, route, { seed });
}

module.exports = { monkeyRoute, installReadOnly, releaseReadOnly };
