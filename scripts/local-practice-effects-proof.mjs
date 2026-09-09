// Local presentation-only acceptance: no issue/respond/acknowledge or account writes.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";
if (process.argv[2] !== "--run-local") {
  console.log("Use --run-local for a new local Chrome presentation tab. No attempt/account writes.");
  process.exit(0);
}
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, "docs/evidence/screenshots", `practice-effects-${new Date().toISOString().replace(/[:.]/g, "-")}`);
const page = await localPage({ pathname: "/practice?set=gaps", newTab: true });
const assert = (value, message) => { if (!value) throw Error(message); };
const captures = [];
let preferences;
try {
  await page.until("location.origin==='http://learner.localhost:3100' && location.pathname==='/practice' && !!document.querySelector('#practice-start-title')", 60000);
  assert(await page.evaluate("(async()=>{const r=await fetch('/v1/me',{cache:'no-store'});const v=await r.json();return v.email==='learner@ac.localhost'})()"), "Synthetic learner required");
  preferences = await page.evaluate("({sound:localStorage.getItem('ac-practice-sounds'),companion:localStorage.getItem('ac-practice-companion')})");
  const click = async label => {
    const node = page.button(label);
    await page.until(`!!(${node})`);
    const point = await page.evaluate(`(()=>{const b=${node};b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await page.send("Input.dispatchMouseEvent", {type:"mousePressed",button:"left",clickCount:1,...point});
    await page.send("Input.dispatchMouseEvent", {type:"mouseReleased",button:"left",clickCount:1,...point});
  };
  const capture = async name => {
    const layout = await page.evaluate("(()=>{const r=document.documentElement; const d=document.querySelector('dialog[open]');return {width:r.clientWidth,scroll:r.scrollWidth,dialog:d?{scroll:d.scrollHeight,height:d.clientHeight,bottom:d.getBoundingClientRect().bottom}:null,height:innerHeight}})()");
    assert(layout.scroll <= layout.width, "Horizontal overflow");
    if (layout.dialog) assert(layout.dialog.bottom <= layout.height, "Dialog clipped");
    const shot = await page.send("Page.captureScreenshot", {format:"png",captureBeyondViewport:false});
    await writeFile(path.join(output,`${name}.png`),Buffer.from(shot.data,"base64"));
    captures.push({name,...layout});
  };
  await mkdir(output,{recursive:true});
  await page.send("Emulation.setDeviceMetricsOverride",{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await capture("preflight-desktop");
  await click("Leave practice"); await page.until("!!document.querySelector('dialog[open]')");
  await capture("pause-desktop");
  await page.send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27});
  await page.send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27});
  await page.until("!document.querySelector('dialog[open]') && document.activeElement?.getAttribute('aria-label')==='Leave practice'");
  await page.until("!document.querySelector('dialog')");
  for (const width of [390,320]) {
    await page.send("Emulation.setDeviceMetricsOverride",{width,height:740,deviceScaleFactor:1,mobile:false});
    await page.delay(250);
    await click("Leave practice"); await page.until("!!document.querySelector('dialog[open]')");
    await capture(`pause-${width}`); await click("Keep practising");
    await page.until("!document.querySelector('dialog')");
  }
  await page.send("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"reduce"}]});
  await click("Leave practice"); await page.until("!!document.querySelector('dialog[open]')");
  assert(await page.evaluate("[...document.querySelectorAll('dialog svg *')].every(e=>getComputedStyle(e).animationName==='none')"),"Reduced motion animated");
  await capture("pause-320-reduced"); await click("Keep practising");
  // Exercise the mounted audio toggle via native input; loading never autoplays.
  const enabled = await page.evaluate("!!document.querySelector('[aria-label=\"Mute practice sounds\"]')");
  if (enabled) await click("Mute practice sounds");
  await click("Enable practice sounds");
  await page.until("performance.getEntriesByType('resource').filter(e=>/\\/audio\\/practice\\/(select|confirm|reward)\\.wav$/.test(e.name)).length===3");
  await click("Mute practice sounds");
  assert(page.external()===0,"Unexpected external request");
  await writeFile(path.join(output,"proof.json"),JSON.stringify({scope:"local presentation only",nativeMouse:true,nativeEscapeFocus:true,reducedMotion:true,samplesRequested:3,subjectiveListeningReview:false,attemptWrites:0,captures},null,2));
  console.log(JSON.stringify({output,captures:captures.length,passed:true}));
} finally {
  if (preferences) await page.evaluate(`(()=>{const before=${JSON.stringify(preferences)}; for(const [key,value] of [['ac-practice-sounds',before.sound],['ac-practice-companion',before.companion]]){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value)}window.dispatchEvent(new Event('ac-practice-sounds-change'));})()`).catch(()=>{});
  await page.send("Emulation.clearDeviceMetricsOverride").catch(()=>{});
  await page.send("Emulation.setEmulatedMedia",{features:[]}).catch(()=>{});
  await page.close();
}
