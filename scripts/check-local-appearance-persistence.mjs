import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({pathname:"/settings",newTab:true});
const ready = "document.readyState==='complete' && Boolean(document.querySelector('select[aria-label=\"Theme\"]'))";
const observe = () => page.evaluate("({theme:document.documentElement.dataset.theme,accent:document.documentElement.dataset.accent,selectedTheme:document.querySelector('select[aria-label=\"Theme\"]')?.value,selectedAccent:document.querySelector('select[aria-label=\"Accent color\"]')?.value,storedTheme:localStorage.getItem('ac-appearance-theme'),storedAccent:localStorage.getItem('ac-appearance-accent'),status:[...document.querySelectorAll('[role=alert],[role=status]')].map(e=>e.textContent)})");
const select = async(label,value) => {
  await page.evaluate(`(()=>{const e=document.querySelector('select[aria-label=${JSON.stringify(label)}]');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`,true);
};
try {
  await page.until(ready); await page.delay(2000);
  process.stdout.write(JSON.stringify({before:await observe()})+"\n");
  await select("Theme","light"); await page.delay(300); await select("Accent color","cobalt"); await page.delay(500);
  process.stdout.write(JSON.stringify({after_ui:await observe()})+"\n");
  const before = await page.evaluate("performance.timeOrigin");
  await page.send("Page.reload"); await page.until(`performance.timeOrigin!==${before} && ${ready}`); await page.delay(2000);
  const after = await observe();
  process.stdout.write(JSON.stringify({after_new_document:after})+"\n");
  if(after.theme!=="light"||after.accent!=="cobalt"||after.storedTheme!=="light"||after.storedAccent!=="cobalt") throw new Error("Appearance persistence mismatch");
  process.stdout.write("Light/cobalt retained in new document after normal Settings changes.\n");
} catch { process.stderr.write("Appearance persistence check incomplete.\n"); process.exitCode=1; }
finally { await page.close(); }
