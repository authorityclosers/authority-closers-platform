import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/practice?set=next-move", newTab: true });
try {
  await page.until("document.readyState==='complete' && Boolean(document.querySelector('input[type=radio]'))");
  await page.delay(1500);
  await page.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  const initialHeadingFocus = await page.evaluate("document.activeElement?.id.startsWith('prompt-')");
  await page.evaluate("document.querySelector('input[type=radio]').focus()");
  await page.until("document.activeElement?.matches('input[type=radio]')");
  for (const type of ["keyDown","keyUp"]) await page.send("Input.dispatchKeyEvent", { type, key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
  let nativeRadioSelection = true;
  try { await page.until("[...document.querySelectorAll('input[type=radio]')][1]?.checked", 5000); }
  catch { nativeRadioSelection = false; await page.evaluate("[...document.querySelectorAll('input[type=radio]')][1].click()", true); }
  await page.click("Check my response");
  await page.until("document.activeElement?.getAttribute('role')==='status'");
  await page.click("Next prompt");
  await page.until("document.activeElement?.id.startsWith('prompt-') && document.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow')==='1'");
  process.stdout.write(JSON.stringify({ status:"focus-passed", initial_heading_focus:initialHeadingFocus, native_arrow_radio_selection:nativeRadioSelection, feedback_focus:true, next_prompt_focus:true }) + "\n");
} catch { process.stderr.write("Native keyboard/focus probe incomplete; no broader native certification claimed.\n"); process.exitCode=1; }
finally { await page.send("Emulation.setFocusEmulationEnabled", { enabled:false }).catch(()=>{}); await page.close(); }
