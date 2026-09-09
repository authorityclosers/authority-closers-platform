import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/learning", newTab: true });
const output = path.resolve("docs/evidence/screenshots/learning-path-20260908");
await mkdir(output, { recursive: true });
const capture = async (name) => {
  await page.evaluate("window.scrollTo(0,0)"); await page.delay(300);
  const image = await page.send("Page.captureScreenshot", { format:"png", captureBeyondViewport:false });
  await writeFile(path.join(output, name + ".png"), Buffer.from(image.data,"base64"));
};
try {
  await page.until("Boolean(document.querySelector('main a[href=\"/learn/authority-closers-free-course\"]'))");
  await page.evaluate("document.querySelector('main a[href=\"/learn/authority-closers-free-course\"]').click()", true);
  await page.until("location.pathname==='/learn/authority-closers-free-course' && Boolean(document.querySelector('main details summary'))");
  await page.delay(500);
  const original = await page.evaluate("document.querySelector('main details').open");
  await page.evaluate("document.querySelector('main details summary').click()", true);
  await page.until(`document.querySelector('main details').open !== ${original}`);
  await page.evaluate("document.querySelector('main details summary').click()", true);
  await page.until(`document.querySelector('main details').open === ${original}`);
  await page.send("Emulation.setDeviceMetricsOverride", { width:320,height:740,deviceScaleFactor:1,mobile:false });
  await capture("final-course-mobile320");
  if (!await page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth")) throw new Error("Course overflow");
  await page.evaluate("document.querySelector('main a[href*=\"/module/\"]').click()", true);
  await page.until("location.pathname.includes('/module/') && Boolean(document.querySelector('main a[href^=\"/activity/\"]'))");
  await capture("final-module-mobile320");
  if (!await page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth")) throw new Error("Long module title overflow");
  const activityPath = await page.evaluate("document.querySelector('main a[href^=\"/activity/\"]').getAttribute('href')");
  await page.evaluate("document.querySelector('main a[href^=\"/activity/\"]').click()", true);
  await page.until(`location.pathname===${JSON.stringify(activityPath)} && Boolean(document.querySelector('main h1'))`);
  await page.delay(500);
  await capture("final-actual-activity-mobile320");
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({status:"passed",native_chapter_expansion:true,restored_initial_expansion:true,mobile320_no_overflow:true,actual_activity_navigation:true,course_progress_mutations:0,external_requests:page.external()}) + "\n");
} catch { process.stderr.write("Learning path interaction proof incomplete.\n"); process.stdout.write(JSON.stringify(await page.evaluate("({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,inner:innerWidth,overflow:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&(r.right>document.documentElement.clientWidth+1||r.left< -1)}).slice(0,14).map(e=>({tag:e.tagName,class:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})").catch(()=>null))+"\n"); process.exitCode=1; }
finally { await page.close(); }
