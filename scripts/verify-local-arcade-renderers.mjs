import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/practice", newTab: true });
const output = path.resolve("docs/evidence/screenshots/arcade-interactions-20260908");
await mkdir(output, { recursive: true });
const proof = [];
try {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  for (const [set, kind] of [["next-move", "choice"], ["gaps", "gap"], ["match", "match"], ["build", "build"], ["sequence", "order"], ["listen", "audio"], ["dialogue", "branch"]]) {
    const previous = await page.evaluate("performance.timeOrigin");
    await page.send("Page.navigate", { url: "http://learner.localhost:3100/practice?set=" + set });
    await page.until(`performance.timeOrigin !== ${previous} && document.readyState === 'complete'`);
    await page.until(`Boolean(${page.button(kind === "branch" ? "Send response" : "Check my response")})`);
    if (kind === "match") {
      const group = "document.querySelector('[aria-label=\"Match each statement to a question\"]')";
      const count = await page.evaluate(`${group}.children[0].querySelectorAll('button').length`);
      for (let index = 0; index < count; index++) {
        await page.evaluate(`${group}.children[0].querySelectorAll('button')[${index}].click()`, true); await page.delay(80);
        await page.evaluate(`${group}.children[1].querySelectorAll('button')[${index}].click()`, true); await page.delay(80);
      }
    } else if (kind === "build" || kind === "order") {
      const bank = "document.querySelector('[aria-label=\"Available pieces\"]')";
      const count = await page.evaluate(`${bank}.querySelectorAll('button').length`);
      for (let index = 0; index < count; index++) {
        await page.evaluate(`${bank}.querySelectorAll('button')[${index}].click()`, true); await page.delay(80);
      }
    } else {
      if (kind === "audio") {
        await page.evaluate("document.querySelector('audio').play()", true);
        await page.until("document.querySelector('audio').currentTime > 0.5");
        await page.evaluate("document.querySelector('audio').pause()");
      }
      await page.evaluate("document.querySelector('input[type=radio]').click()", true);
    }
    await page.click(kind === "branch" ? "Send response" : "Check my response");
    if (kind === "branch") {
      for (let step = 0; step < 12; step++) {
        await page.until(`Boolean(${page.button("Next prompt")}) || Boolean(document.querySelector('input[type=radio]:not(:disabled)'))`);
        if (await page.evaluate(`Boolean(${page.button("Next prompt")})`)) break;
        await page.evaluate("document.querySelector('input[type=radio]').click()", true);
        await page.click("Send response");
      }
    }
    await page.until(`Boolean(${page.button("Next prompt")})`);
    const bounds = await page.evaluate(`(()=>{const r=${page.button("Next prompt")}.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:innerHeight};})()`);
    if (bounds.top < 0 || bounds.bottom > bounds.height) throw new Error("Feedback action outside viewport");
    const image = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(path.join(output, kind + "-feedback-mobile390.png"), Buffer.from(image.data, "base64"));
    await page.click("Next prompt");
    await page.until("document.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow') === '1'");
    proof.push({ kind, first_prompt_feedback_and_next: true, bounded_cta: true });
    process.stdout.write(`${kind} response, server feedback and next prompt verified\n`);
  }
  await page.click("Leave practice");
  await page.until("Boolean(document.querySelector('dialog[open]'))");
  const honestExit = await page.evaluate("document.querySelector('dialog').textContent.includes('Your course progress won’t change.') && !document.querySelector('dialog').textContent.toLowerCase().includes('credit')");
  if (!honestExit) throw new Error("Expected honest exit warning");
  await page.click("Keep practising");
  await page.until("!document.querySelector('dialog[open]')");
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ status: "passed", renderers: proof, honest_exit: true, external_requests: page.external(), native_input_certification: false }) + "\n");
} catch { process.stderr.write("Local Arcade renderer proof incomplete; no private diagnostics emitted.\n"); process.exitCode = 1; }
finally { await page.close(); }
