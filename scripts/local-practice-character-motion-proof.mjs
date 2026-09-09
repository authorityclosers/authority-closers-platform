// Captures the actual mounted character. Does not create or modify learning attempts.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";
if (process.argv[2] !== "--run-local") { console.log("Use --run-local for isolated local character-motion acceptance; no account/attempt writes."); process.exit(0); }
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(repository,"docs/evidence/screenshots",`character-motion-${new Date().toISOString().replace(/[:.]/g,"-")}`);
const page = await localPage({pathname:"/practice?set=gaps",newTab:true});
const check = (value,why) => {if(!value) throw Error(why);};
let saved;
const metrics = {};
try {
  await page.until("location.origin==='http://learner.localhost:3100' && !!document.querySelector('#practice-start-title')",60000);
  saved = await page.evaluate("localStorage.getItem('ac-practice-companion-motion')");
  const click = async label => {
    const node = page.button(label); await page.until(`!!(${node})`);
    const point = await page.evaluate(`(()=>{const b=${node};b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await page.send("Input.dispatchMouseEvent",{type:"mousePressed",button:"left",clickCount:1,...point});
    await page.send("Input.dispatchMouseEvent",{type:"mouseReleased",button:"left",clickCount:1,...point});
  };
  await page.send("Emulation.setDeviceMetricsOverride",{width:1000,height:900,deviceScaleFactor:1,mobile:false});
  await page.delay(200);
  await click("Leave practice"); await page.until("!!document.querySelector('dialog[open]')");
  if (await page.evaluate("!!document.querySelector('dialog button[aria-label=\"Resume character animation\"]')")) await click("Resume character animation");
  const svg = "document.querySelector('dialog svg[data-companion]')";
  await page.until(`${svg}?.dataset.play==='running'`);
  metrics.runningAnimations = await page.evaluate(`${svg}.getAnimations({subtree:true}).filter(a=>a.playState==='running').map(a=>a.animationName)`);
  check(metrics.runningAnimations.length>=4,"Character layers not running");
  metrics.backgroundPaused = await page.evaluate("[...document.querySelectorAll('section svg[data-companion]')].every(e=>e.dataset.play==='paused')");
  check(metrics.backgroundPaused,"Background companion still animating through dialog");
  const before = await page.evaluate(`${svg}.getAnimations({subtree:true}).map(a=>a.currentTime)`);
  await page.delay(240);
  const after = await page.evaluate(`${svg}.getAnimations({subtree:true}).map(a=>a.currentTime)`);
  check(after.some((time,i)=>time>before[i]+100),"Animation timeline not advancing");
  await page.send("Input.dispatchMouseEvent",{type:"mouseMoved",x:900,y:140}); await page.delay(200);
  metrics.gaze = await page.evaluate(`({x:${svg}.style.getPropertyValue('--gaze-x'),y:${svg}.style.getPropertyValue('--gaze-y')})`);
  check(parseFloat(metrics.gaze.x)>0 && Math.abs(parseFloat(metrics.gaze.x))<=2.8,"Gaze not bounded/reactive");
  await mkdir(output,{recursive:true});
  const clip = await page.evaluate("(()=>{const r=document.querySelector('dialog').getBoundingClientRect();return {x:Math.floor(r.x)-2,y:Math.floor(r.y)-2,width:Math.ceil(r.width)+4,height:Math.ceil(r.height)+4,scale:1}})()");
  const frames=[];
  for(let index=0;index<32;index++) {
    const time=Date.now(); const image=await page.send("Page.captureScreenshot",{format:"png",clip,captureBeyondViewport:false});
    const name=`frame-${String(index).padStart(3,"0")}.png`; await writeFile(path.join(output,name),Buffer.from(image.data,"base64")); frames.push({name,time});
    await page.delay(150);
  }
  await writeFile(path.join(output,"frames.ffconcat"),"ffconcat version 1.0\n"+frames.map((f,i)=>`file '${f.name}'\nduration ${i<frames.length-1?(frames[i+1].time-f.time)/1000:.15}\n`).join("")+`file '${frames.at(-1).name}'\n`);
  await click("Pause character animation"); await page.until(`${svg}?.dataset.motion==='off'`);
  metrics.paused = await page.evaluate(`${svg}.getAnimations({subtree:true}).filter(a=>a.playState==='running').length===0`);
  check(metrics.paused,"Pause did not stop animations");
  await click("Resume character animation"); await page.until(`${svg}?.dataset.play==='running'`);
  await page.send("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"reduce"}]});
  await page.until(`${svg}?.dataset.play==='paused'`);
  metrics.reduced = await page.evaluate(`${svg}.getAnimations({subtree:true}).filter(a=>a.playState==='running').length===0`);
  check(metrics.reduced,"OS reduced motion did not stop animations");
  await writeFile(path.join(output,"proof.json"),JSON.stringify({scope:"native local DOM animation/input proof",attemptWrites:0,metrics,frameCount:frames.length,durationMs:frames.at(-1).time-frames[0].time},null,2));
  console.log(JSON.stringify({output,metrics,passed:true}));
} finally {
  if(saved!==undefined) await page.evaluate(`(()=>{if(${JSON.stringify(saved)}===null)localStorage.removeItem('ac-practice-companion-motion');else localStorage.setItem('ac-practice-companion-motion',${JSON.stringify(saved)});window.dispatchEvent(new Event('ac-practice-companion-change'));})()`).catch(()=>{});
  await page.send("Emulation.clearDeviceMetricsOverride").catch(()=>{}); await page.send("Emulation.setEmulatedMedia",{features:[]}).catch(()=>{}); await page.close();
}
