// Self-test of the four design rules on a real page: build each fault on /dashboard at 360 px (read-only, nothing is saved) and check the rule fires, then check the same page without the faults and with look-alike lay-outs that are fine. Prints PASS or FAIL per case.
const session = require("./lib/session.cjs");
const design = require("./lib/design.cjs");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const scan = (page) => page.evaluate(design.DESIGN_SCAN);
const names = (r, k) => (r[k] || []).map((x) => x.s).join(" | ").slice(0, 120);
const run = (page, fn) => page.evaluate(fn);
(async () => {
  let tab = null;
  for (let a = 0; a < 6 && !tab; a++) { try { tab = await session.openTab({ alias: "priya", device: "360 px", theme: "light", state: "normal" }); } catch { await sleep(15000); } }
  await tab.context.route("**/*", (rt) => (["GET", "HEAD", "OPTIONS"].includes(rt.request().method()) ? rt.fallback() : rt.abort("blockedbyclient")));
  await session.go(tab, "/dashboard", { wait: 40000 });
  await sleep(8000);
  const page = tab.page;
  const check = (label, ok, extra) => console.log(`${ok ? "PASS" : "FAIL"} ${label}${extra ? " | " + extra : ""}`);
  const base = await scan(page);
  console.log("baseline /dashboard:", JSON.stringify({ edgeMask: base.edgeMask.length, boxed: base.boxed.length, deadRow: base.deadRow.length, labelHeading: base.labelHeading.length }));
  const inv = require("./lib/invariants.cjs");
  const viaScan = (await page.evaluate(inv.scan, true)).design;
  check("the copy inside the robot's page scan gives the same answer as the capture stage's", !!viaScan && JSON.stringify(viaScan) === JSON.stringify(await scan(page)), viaScan ? "" : "no design block in the scan");

  await run(page, () => {
    const m = document.querySelector("main") || document.body;
    const d = document.createElement("div");
    d.id = "qa-t1";
    d.style.cssText = "overflow-x:auto;height:80px;width:100%;-webkit-mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent);mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent)";
    d.innerHTML = '<div style="width:1000px;height:60px;background:#ddd"></div>';
    m.prepend(d);
  });
  let r = await scan(page);
  check("edge-mask: mask-image on a sideways-scrolling row fires", r.edgeMask.length > base.edgeMask.length, names(r, "edgeMask"));
  await run(page, () => { const d = document.getElementById("qa-t1"); d.style.webkitMaskImage = "none"; d.style.maskImage = "none"; });
  r = await scan(page);
  check("edge-mask: the same row without a mask does not fire", r.edgeMask.length === base.edgeMask.length, names(r, "edgeMask"));
  await run(page, () => { const d = document.getElementById("qa-t1"); d.style.overflowX = "hidden"; d.style.webkitMaskImage = "linear-gradient(90deg,transparent,#000)"; d.style.maskImage = d.style.webkitMaskImage; });
  r = await scan(page);
  check("edge-mask: a masked row that does not scroll does not fire", r.edgeMask.length === base.edgeMask.length, names(r, "edgeMask"));
  await run(page, () => document.getElementById("qa-t1").remove());

  await run(page, () => {
    document.body.style.background = "rgb(230,230,235)";
    const m = document.querySelector("main") || document.body;
    m.dataset.qaOld = m.getAttribute("style") || "";
    m.style.cssText += ";margin:0 28px;background:#fff;border-radius:16px;box-shadow:0 1px 4px rgba(0,0,0,.2);min-height:90vh;width:auto";
  });
  r = await scan(page);
  check("boxed: content in a card with grey sides fires", r.boxed.length > 0, names(r, "boxed"));
  await run(page, () => { const m = document.querySelector("main") || document.body; m.style.cssText = m.dataset.qaOld || ""; m.style.margin = "0 16px"; m.style.background = "#fff"; m.style.minHeight = "90vh"; });
  r = await scan(page);
  check("boxed: the same card with 16 px margins (the normal gutter) does not fire", r.boxed.length === 0, names(r, "boxed"));
  await run(page, () => { const m = document.querySelector("main") || document.body; m.style.cssText = m.dataset.qaOld || ""; document.body.style.background = ""; });

  await run(page, () => {
    const m = document.querySelector("main") || document.body;
    const w = document.createElement("div");
    w.id = "qa-t3";
    w.style.cssText = "display:flex;flex-direction:column;gap:8px;padding:8px 0";
    w.innerHTML = '<div style="display:flex;gap:4px"><button style="width:70px;height:36px">Team</button><button style="width:70px;height:36px">Me</button></div><div><button style="width:96px;height:36px">Controls</button></div>';
    m.prepend(w);
  });
  r = await scan(page);
  check("dead-row: Team | Me with Controls on its own row fires", r.deadRow.some((x) => /Controls/.test(x.s)), names(r, "deadRow"));
  await run(page, () => { const w = document.getElementById("qa-t3"); w.firstChild.style.width = "100%"; w.firstChild.style.display = "grid"; w.firstChild.style.gridTemplateColumns = "1fr 1fr"; });
  r = await scan(page);
  check("dead-row: the row above full width (no free space) does not fire", !r.deadRow.some((x) => /Controls/.test(x.s)), names(r, "deadRow"));
  await run(page, () => { const w = document.getElementById("qa-t3"); w.firstChild.style.cssText = "display:flex;gap:4px"; w.style.flexDirection = "row"; w.style.flexWrap = "wrap"; });
  r = await scan(page);
  check("dead-row: a wrapping group does not fire", !r.deadRow.some((x) => /Controls/.test(x.s)), names(r, "deadRow"));
  await run(page, () => document.getElementById("qa-t3").remove());

  await run(page, () => {
    const m = document.querySelector("main") || document.body;
    const w = document.createElement("div");
    w.id = "qa-t4";
    w.innerHTML = '<h2 id="qa-h" style="font-size:26px;margin:0 0 6px">Overview</h2><button style="height:44px;width:120px">Go</button>';
    m.prepend(w);
  });
  r = await scan(page);
  check("label-heading: a 26 px one-word heading above a button fires", r.labelHeading.some((x) => /Overview/.test(x.s)), names(r, "labelHeading"));
  await run(page, () => { document.getElementById("qa-h").style.fontSize = "13px"; });
  r = await scan(page);
  check("label-heading: the same heading at 13 px does not fire", !r.labelHeading.some((x) => /Overview/.test(x.s)), names(r, "labelHeading"));
  await run(page, () => { const h = document.getElementById("qa-h"); h.style.fontSize = "26px"; h.innerHTML = '<button style="font:inherit">Overview</button>'; });
  r = await scan(page);
  check("label-heading: a heading that is a button does not fire", !r.labelHeading.some((x) => /Overview/.test(x.s)), names(r, "labelHeading"));
  await run(page, () => { const h = document.getElementById("qa-h"); const n = document.createElement("h1"); n.id = "qa-h"; n.style.cssText = "font-size:26px;margin:0 0 6px"; n.textContent = "Overview"; h.replaceWith(n); });
  r = await scan(page);
  check("label-heading: an h1 page title does not fire", !r.labelHeading.some((x) => /Overview/.test(x.s)), names(r, "labelHeading"));
  await run(page, () => { const h = document.getElementById("qa-h"); const n = document.createElement("h2"); n.id = "qa-h"; n.style.cssText = "font-size:26px;margin:0 0 6px"; n.textContent = "Overview of the week"; h.replaceWith(n); });
  r = await scan(page);
  check("label-heading: three words do not fire", !r.labelHeading.some((x) => /Overview/.test(x.s)), names(r, "labelHeading"));

  await session.closeTab(tab);
  await session.shutdown();
  process.exit(0);
})();
