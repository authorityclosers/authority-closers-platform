export const reviewHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sales Xray · Review workbench</title>
<style>
*{box-sizing:border-box}
:root{color-scheme:light;--page:#f3f5f7;--surface:#fff;--canvas:#e9edf1;--text:#1c2730;--muted:#5c6973;--border:#d5dde3;--accent:#315a6c;--accent-soft:#e8f0f3;--focus:#087e8b;--shadow:0 2px 8px #15212b12}
html{min-width:320px;background:var(--page);color:var(--text)}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--page);color:var(--text)}
button,input{font:inherit}
a{color:var(--accent)}
button{color:inherit}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.page{max-width:1800px;margin:0 auto;padding:12px clamp(12px,2vw,28px) 18px}
.page-header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;margin:0 0 8px}
.eyebrow{margin:0 0 6px;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
h1{margin:0;font-size:clamp(23px,2.5vw,32px);line-height:1.15;letter-spacing:-.025em}
.intro{max-width:760px;margin:0;color:var(--muted);font-size:14px}
.review-note{margin:0 0 10px;padding:7px 12px;background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:10px;box-shadow:var(--shadow)}
.review-note summary{cursor:pointer;color:var(--muted);font-size:13px;font-weight:650}
.review-note ol{margin:0;padding-left:21px}
.review-note li{padding-left:3px}
.workbench{display:grid;grid-template-columns:minmax(235px,270px) minmax(0,1fr);gap:12px;align-items:start}
.sidebar,.canvas-panel{min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow)}
.sidebar{padding:0;position:sticky;top:10px;max-height:calc(100dvh - 96px);overflow:auto}
#state-navigation{padding:14px}
#state-navigation>summary{display:flex;min-height:42px;align-items:center;cursor:pointer;list-style-position:inside;font-size:16px;font-weight:700}
.sidebar-content{padding-top:6px}
.side-heading{margin:0 0 4px;font-size:17px}
.muted{color:var(--muted)}
.sidebar-copy{margin:4px 0 13px;color:var(--muted);font-size:13px}
#state-list{display:grid;gap:6px;margin:12px 0 18px}
#fixture-navigation{margin:0 0 14px;padding:0 0 12px;border-bottom:1px solid var(--border)}
#fixture-navigation>summary{min-height:40px;cursor:pointer;font-weight:700}
#fixture-list{display:grid;gap:5px;margin:8px 0 0}
.fixture-group{margin:9px 0 2px;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.fixture-group:first-child{margin-top:0}
.state-choice{width:100%;padding:10px 11px;text-align:left;border:1px solid var(--border);border-radius:9px;background:var(--surface);cursor:pointer;overflow-wrap:anywhere}
.state-choice:hover{background:#f6f8f9;border-color:#aebbc4}
.state-choice[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 3px 0 var(--accent);font-weight:650}
.state-kind{display:block;margin-top:2px;color:var(--muted);font-size:12px;font-weight:400}
.divider{height:1px;margin:18px 0;background:var(--border);border:0}
label{display:block;margin:0 0 5px;font-weight:650}
input[type="text"]{width:100%;min-width:0;padding:10px 11px;border:1px solid #aebbc4;border-radius:8px;background:var(--surface);color:var(--text)}
input[readonly]{background:#f7f8f9}
.button-row{display:flex;flex-wrap:wrap;gap:7px;margin:9px 0}
.button{min-height:40px;padding:8px 12px;border:1px solid #aebbc4;border-radius:8px;background:var(--surface);color:var(--text);font-weight:600;cursor:pointer}
.button:hover:not(:disabled){background:#f3f6f7;border-color:#74848f}
.button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.button.primary:hover:not(:disabled){background:#274b5b}
.button:disabled{cursor:default;opacity:.48}
.status{min-height:24px;margin:8px 0;color:var(--muted);font-size:13px}
.canvas-panel{overflow:hidden}
.toolbar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border)}
.selection-title{min-width:0}
.selection-title .eyebrow{margin-bottom:3px}
#selected-name{display:block;overflow-wrap:anywhere;font-size:18px;font-weight:700}
.toolbar-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}
.url-bar{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;gap:7px;align-items:center;padding:12px 18px;border-bottom:1px solid var(--border)}
.url-label{color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap}
#direct-url{width:100%;padding:8px 10px;font:13px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
.canvas-controls{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 14px;background:#f8f9fa;border-bottom:1px solid var(--border)}
.canvas-controls p{margin:0;color:var(--muted);font-size:13px}
.segmented{display:inline-flex;gap:3px;padding:3px;border:1px solid var(--border);border-radius:9px;background:var(--surface)}
.segmented .button{min-height:34px;padding:5px 10px;border:0}
.segmented .button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent)}
.canvas-viewport{min-width:0;min-height:68vh;padding:16px;background:var(--canvas);overflow:auto}
.frame-stage{width:100%;min-height:68vh;display:flex;justify-content:center;align-items:flex-start;margin:0 auto}
#sales-xray-canvas{display:block;width:100%;height:max(68vh,650px);min-height:560px;border:1px solid #c4cdd3;border-radius:7px;background:#fff;box-shadow:0 4px 16px #192a351c}
.canvas-viewport[data-width="mobile"] .frame-stage{width:min(390px,100%)}
.canvas-viewport[data-width="mobile"] #sales-xray-canvas{width:100%;height:max(78vh,740px);min-height:640px}
.canvas-foot{margin:0;padding:9px 16px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
.help{margin:18px 0 0;color:var(--muted);font-size:13px}
@media(max-width:760px){.workbench{grid-template-columns:minmax(0,1fr)}.sidebar{position:static;max-height:none}.sidebar #state-list{grid-template-columns:repeat(2,minmax(0,1fr))}.canvas-viewport,.frame-stage{min-height:65vh}#sales-xray-canvas{height:70vh}}
@media(max-width:560px){.page{padding:10px 10px 20px}.page-header{gap:4px 10px;margin-bottom:7px}.page-header>.eyebrow{font-size:10px}h1{font-size:23px}.intro{flex-basis:100%;font-size:12px}.review-note{margin:0 0 8px;padding:6px 9px}.sidebar #state-navigation{padding:9px 11px}.sidebar #state-list{grid-template-columns:minmax(0,1fr);max-height:220px;overflow:auto}.toolbar{grid-template-columns:minmax(0,1fr) auto;padding:9px 10px}.toolbar-actions{justify-content:flex-end}.url-bar{grid-template-columns:minmax(0,1fr) auto;padding:9px 10px}.url-label{grid-column:1/-1}.url-bar #direct-url{grid-column:1/-1;grid-row:2}.url-bar .button{grid-row:3}.canvas-controls{align-items:center;justify-content:center;padding:7px 10px}.canvas-controls p{display:none}.canvas-viewport{padding:8px}.canvas-viewport[data-width="mobile"] .frame-stage{width:min(390px,100%)}.canvas-viewport[data-width="mobile"] #sales-xray-canvas{height:75vh;min-height:580px}}
@media(min-width:761px) and (max-height:760px){.page{padding:8px 12px 10px}.page-header{gap:8px 12px;margin-bottom:6px}.page-header>.eyebrow{font-size:10px}h1{font-size:23px}.intro{font-size:12px}.review-note{margin-bottom:8px;padding:5px 10px}.workbench{grid-template-columns:minmax(205px,225px) minmax(0,1fr);gap:10px}.sidebar{top:8px;max-height:calc(100dvh - 82px)}#state-navigation{padding:9px}.sidebar-copy{margin:3px 0 7px;font-size:12px}#state-list{gap:4px;margin:7px 0 9px}.state-choice{padding:7px 9px}.state-kind{font-size:11px}.divider{margin:10px 0}.status{min-height:18px;margin:5px 0;font-size:12px}.toolbar{padding:8px 11px}.url-bar{gap:5px;padding:7px 10px}.canvas-controls{padding:6px 9px}.canvas-viewport{min-height:0;padding:7px}.frame-stage{min-height:0}#sales-xray-canvas{height:calc(100dvh - 370px);min-height:300px}.canvas-foot{padding:5px 10px}.help{display:none}}
</style>
</head>
<body>
<main class="page">
  <header class="page-header">
    <p class="eyebrow">Sales Xray · Review</p>
    <h1>State workbench</h1>
    <p class="intro">Open paused local examples and captured observations in the actual Sales Xray app.</p>
  </header>
  <details class="review-note">
    <summary>UI review notes · 1</summary>
    <ol id="annotations">
      <li><strong>Top section · “Add a call to review…” heading area.</strong> First review item: inspect its hierarchy, spacing and responsive wrapping on the actual empty upload screen.</li>
    </ol>
  </details>
  <div class="workbench">
    <aside class="sidebar" aria-label="Observed state navigation">
      <details id="state-navigation">
        <summary>Observed states &amp; call inspection</summary>
        <div class="sidebar-content">
          <p class="sidebar-copy">Inspect the mounted app using paused local examples or observations from this browser and calls you own.</p>
          <details id="fixture-navigation">
            <summary>Local test states</summary>
            <p class="sidebar-copy">Fixed examples for UI review. No call is uploaded or analysed.</p>
            <nav id="fixture-list" aria-label="Choose a local Sales Xray test state"></nav>
          </details>
          <nav id="state-list" aria-label="Choose an observed Sales Xray state"></nav>
          <p id="state-status" class="status" role="status" aria-live="polite">Opening the live upload screen.</p>
          <hr class="divider">
          <form id="capture">
            <label for="call">Saved call URL or call ID</label>
            <input id="call" type="text" autocomplete="off" placeholder="Paste a saved call URL" required>
            <div class="button-row">
              <button class="button primary" type="submit">Load observed states</button>
              <button class="button" type="button" id="reset">Clear call inspection</button>
            </div>
          </form>
          <p id="status" class="status" role="status" aria-live="polite">Sign in through Sales Xray, then choose a call you own.</p>
          <p id="local-status" class="status" role="status" aria-live="polite">Browser-local observations appear after the actual app reports them.</p>
        </div>
      </details>
    </aside>
    <section class="canvas-panel" aria-label="Sales Xray application canvas">
      <div class="toolbar">
        <div class="selection-title">
          <p class="eyebrow">Selected state</p>
          <span id="selected-name">Upload screen</span>
        </div>
        <div class="toolbar-actions">
          <button class="button" type="button" id="previous" aria-label="Previous state">Previous</button>
          <button class="button" type="button" id="next" aria-label="Next state">Next</button>
        </div>
      </div>
      <div class="url-bar">
        <span class="url-label">Direct app URL</span>
        <input id="direct-url" type="text" readonly aria-label="Direct app URL">
        <button class="button" type="button" id="copy-url">Copy</button>
        <button class="button primary" type="button" id="fullscreen">Open full screen</button>
      </div>
      <div class="canvas-controls">
        <p>Live app canvas · controls stay outside the application.</p>
        <div class="segmented" role="group" aria-label="Canvas width">
          <button class="button" type="button" id="desktop-width" aria-pressed="true">Desktop</button>
          <button class="button" type="button" id="mobile-width" aria-pressed="false">Mobile · 390 px</button>
        </div>
      </div>
      <div id="canvas-viewport" class="canvas-viewport" data-width="desktop">
        <div class="frame-stage">
          <iframe id="sales-xray-canvas" name="sales-xray-canvas" title="Sales Xray application" src="/?new=1" referrerpolicy="no-referrer" allowfullscreen></iframe>
        </div>
      </div>
      <p class="canvas-foot">The app is loaded from the same local origin. State URLs are reflected in this workbench address so a selection can be bookmarked.</p>
    </section>
  </div>
  <p class="help">Local test states are synthetic and paused. Observed states still require their browser snapshot or live access lease. Neither mode uploads a file, changes consent, or runs analysis.</p>
  <details class="help">
    <summary>What this workbench records</summary>
    <ul>
      <li>Upload UI observations come from the mounted controller. Browser-local snapshots may retain the selected file name and size in volatile browser memory for up to 30 minutes; they never store file bytes, a hash, a challenge token, or consent as an accepted business decision.</li>
      <li>Opening a local snapshot displays observed checkbox and language values without restoring the File object or applying consent. Select the file again in the app after reload.</li>
      <li>Live call observations recheck authorization and source identity with a short access lease. Session expiry, denied access, source changes, and bridge restart make affected observations unavailable.</li>
    </ul>
  </details>
</main>
<script src="/__review/controls.js" defer></script>
</body>
</html>`;

export const reviewScript = `"use strict";
const callInput=document.getElementById("call");
const status=document.getElementById("status");
const localStatus=document.getElementById("local-status");
const stateStatus=document.getElementById("state-status");
const stateList=document.getElementById("state-list");
const fixtureList=document.getElementById("fixture-list");
const fixtureNavigation=document.getElementById("fixture-navigation");
const selectedName=document.getElementById("selected-name");
const directUrl=document.getElementById("direct-url");
const canvas=document.getElementById("sales-xray-canvas");
const viewport=document.getElementById("canvas-viewport");
const stateNavigation=document.getElementById("state-navigation");
const previous=document.getElementById("previous");
const next=document.getElementById("next");
function syncStateNavigation(){stateNavigation.open=window.matchMedia("(min-width: 561px)").matches;}
syncStateNavigation();
window.addEventListener("resize",syncStateNavigation,{passive:true});
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reportSections=new Set(["overview","prospect","moments","skills","next-call-plan"]);
const fixtureDefinitions=[
  ["auth.email","Sign in with email","Account"],
  ["auth.code","Enter email code","Account"],
  ["auth.error","Email verification error","Account"],
  ["profile.required","Complete your profile","Profile"],
  ["profile.unverified","Verify mobile number","Profile"],
  ["profile.ready","Profile ready","Profile"],
  ["upload.empty","Empty upload","Upload"],
  ["upload.selected","Selected audio","Upload"],
  ["upload.validation","Invalid replacement","Upload"],
  ["processing.received","Recording received","Processing"],
  ["processing.transcribing","Transcribing","Processing"],
  ["processing.conversation","Checking conversation","Processing"],
  ["processing.report","Writing report","Processing"],
  ["processing.paused","Analysis paused","Processing"],
  ["processing.failed","Analysis needs attention","Processing"],
];
const fixtureIds=new Set(fixtureDefinitions.map(item=>item[0]));
const fixtureStates=fixtureDefinitions.map(([id,name,group])=>({key:"fixture:"+id,kind:"fixture",name,detail:"Local fixture · "+group+" · paused",href:"/?new=1&sx-fixture="+encodeURIComponent(id),fixtureId:id,group}));
const uploadState={key:"upload",kind:"upload",name:"Upload screen",detail:"Actual mounted app",href:"/?new=1"};
let states=[uploadState], selectedKey="upload", activeCall=false, pendingCall=false, pendingLocal=false;
let callValue=null, localValue=null, currentAppUrl=null, pendingBookmark=null, localLoaded=false;
async function request(path,body){
  const allowed=new Set(["start","reset","catalog","local/catalog"]);
  if(!allowed.has(path))throw Error("Review route is unavailable.");
  const response=await fetch("/__review/api/"+path,{method:body?"POST":"GET",credentials:"same-origin",cache:"no-store",redirect:"error",headers:body?{"content-type":"application/json"}:{},body:body?JSON.stringify(body):undefined});
  const value=await response.json();
  if(!response.ok)throw Error(value.detail||"Review unavailable");
  return value;
}
function safeAppUrl(value){
  let url;
  try{url=new URL(value,location.origin);}catch{return null;}
  if(url.origin!==location.origin||url.pathname!=="/"||url.username||url.password)return null;
  for(const key of new Set(url.searchParams.keys()))if(url.searchParams.getAll(key).length!==1)return null;
  const keys=[...url.searchParams.keys()];
  const hash=new URLSearchParams(url.hash.slice(1));
  if(url.searchParams.has("sx-fixture")){
    if(url.searchParams.get("new")!=="1"||keys.length!==2||keys.some(key=>!new Set(["new","sx-fixture"]).has(key))||url.hash||!fixtureIds.has(url.searchParams.get("sx-fixture")))return null;
    return url;
  }
  if(url.searchParams.has("new")){
    if(url.searchParams.get("new")!=="1"||keys.some(key=>!new Set(["new","sx-review-local"]).has(key))||url.hash)return null;
    const localId=url.searchParams.get("sx-review-local");
    if(localId!==null&&!uuid.test(localId))return null;
    return url;
  }
  if(!uuid.test(url.searchParams.get("call")||"")||keys.some(key=>!new Set(["call","section"]).has(key)))return null;
  const section=url.searchParams.get("section");
  if(section!==null&&(!reportSections.has(section)||url.hash))return null;
  if(url.hash){
    const allowedHash=new Set(["sx-review","mode","frame"]);
    if([...hash.keys()].some(key=>!allowedHash.has(key))||[...new Set(hash.keys())].some(key=>hash.getAll(key).length!==1)||hash.get("sx-review")!=="v1"||hash.get("mode")!=="observed"||!uuid.test(hash.get("frame")||""))return null;
    if([...hash.keys()].length!==3)return null;
  }
  return url;
}
function timeLabel(value){
  const date=new Date(value);
  return Number.isNaN(date.getTime())?"time unavailable":date.toLocaleTimeString();
}
function callFrameState(frame,id){
  if(!frame||!uuid.test(frame.id||"")||typeof frame.state!=="string"||!frame.state||frame.state.length>160)return null;
  const query="/?call="+encodeURIComponent(id);
  const href=frame.state==="report.available"?query:query+"#sx-review=v1&mode=observed&frame="+encodeURIComponent(frame.id);
  const safe=safeAppUrl(href);
  if(!safe)return null;
  return {key:"processing:"+id+":"+frame.id,kind:"processing",name:frame.state,detail:"Live API · observed "+timeLabel(frame.observedAt),href:safe.href,callId:id,frameId:frame.id};
}
function localFrameState(frame){
  if(!frame||!uuid.test(frame.id||"")||typeof frame.label!=="string"||frame.label.length>512)return null;
  const safe=safeAppUrl("/?new=1&sx-review-local="+encodeURIComponent(frame.id));
  if(!safe)return null;
  return {key:"local:"+frame.id,kind:"local",name:frame.label,detail:"Browser-local · observed "+timeLabel(frame.observedAt),href:safe.href,frameId:frame.id};
}
function hashFor(state){
  const params=new URLSearchParams();
  params.set("sx-workbench","v1");
  params.set("kind",state.kind);
  if(state.kind==="processing"){params.set("call",state.callId);params.set("frame",state.frameId);}
  if(state.kind==="local")params.set("frame",state.frameId);
  if(state.kind==="fixture")params.set("id",state.fixtureId);
  params.set("width",viewport.dataset.width==="mobile"?"mobile":"desktop");
  return "#"+params.toString();
}
function writeBookmark(state,replace){
  const hash=hashFor(state);
  if(location.hash===hash)return;
  const method=replace?"replaceState":"pushState";
  history[method](null,"",location.pathname+location.search+hash);
}
function parseBookmark(){
  const params=new URLSearchParams(location.hash.slice(1));
  if(!location.hash)return {kind:"upload",width:"desktop"};
  const allowed=new Set(["sx-workbench","kind","call","frame","id","width"]);
  if([...params.keys()].some(key=>!allowed.has(key))||[...new Set(params.keys())].some(key=>params.getAll(key).length!==1)||params.get("sx-workbench")!=="v1")return null;
  const width=params.get("width")||"desktop";
  if(!["desktop","mobile"].includes(width))return null;
  const kind=params.get("kind");
  if(kind==="upload"&&[...params.keys()].every(key=>["sx-workbench","kind","width"].includes(key)))return {kind,width};
  if(kind==="local"&&params.getAll("frame").length===1&&uuid.test(params.get("frame"))&&[...params.keys()].every(key=>["sx-workbench","kind","frame","width"].includes(key)))return {kind,width,frameId:params.get("frame")};
  if(kind==="fixture"&&params.getAll("id").length===1&&fixtureIds.has(params.get("id"))&&[...params.keys()].every(key=>["sx-workbench","kind","id","width"].includes(key)))return {kind,width,fixtureId:params.get("id")};
  if(kind==="processing"&&uuid.test(params.get("call")||"")&&uuid.test(params.get("frame")||"")&&[...params.keys()].every(key=>["sx-workbench","kind","call","frame","width"].includes(key)))return {kind,width,callId:params.get("call"),frameId:params.get("frame")};
  return null;
}
function stateForKey(key){return states.find(state=>state.key===key)||fixtureStates.find(state=>state.key===key)||null;}
function selectedSequence(){return selectedKey.startsWith("fixture:")?fixtureStates:states;}
function renderFixtures(){
  fixtureList.replaceChildren();
  let group="";
  for(const state of fixtureStates){
    if(state.group!==group){
      group=state.group;
      const heading=document.createElement("p");heading.className="fixture-group";heading.textContent=group;
      fixtureList.append(heading);
    }
    const button=document.createElement("button");
    button.type="button";button.className="state-choice";button.dataset.stateKey=state.key;
    button.setAttribute("aria-pressed",String(state.key===selectedKey));
    button.textContent=state.name;
    button.addEventListener("click",()=>selectState(state,false));
    fixtureList.append(button);
  }
}
function renderStates(){
  renderFixtures();
  stateList.replaceChildren();
  for(const state of states){
    const button=document.createElement("button");
    button.type="button";button.className="state-choice";button.dataset.stateKey=state.key;
    button.setAttribute("aria-pressed",String(state.key===selectedKey));
    button.append(document.createTextNode(state.name));
    const detail=document.createElement("span");detail.className="state-kind";detail.textContent=state.detail;
    button.append(detail);
    button.addEventListener("click",()=>selectState(state,false));
    stateList.append(button);
  }
  const sequence=selectedSequence();
  const index=sequence.findIndex(state=>state.key===selectedKey);
  previous.disabled=index<=0;next.disabled=index<0||index>=sequence.length-1;
}
function selectState(state,replaceBookmark){
  if(!state)return false;
  const known=stateForKey(state.key);
  if(!known)return false;
  const safe=safeAppUrl(known.href);
  if(!safe){stateStatus.textContent="This observed destination is not an allowed local app URL.";return false;}
  selectedKey=known.key;currentAppUrl=safe;
  if(known.kind==="fixture")fixtureNavigation.open=true;
  selectedName.textContent=known.name;
  directUrl.value=safe.href;
  canvas.src=safe.href;
  stateStatus.textContent=known.detail;
  renderStates();
  writeBookmark(known,replaceBookmark);
  return true;
}
function findStateForBookmark(bookmark){
  if(!bookmark)return null;
  if(bookmark.kind==="upload")return states[0];
  if(bookmark.kind==="local")return states.find(state=>state.kind==="local"&&state.frameId===bookmark.frameId)||null;
  if(bookmark.kind==="fixture")return fixtureStates.find(state=>state.fixtureId===bookmark.fixtureId)||null;
  if(bookmark.kind==="processing")return states.find(state=>state.kind==="processing"&&state.callId===bookmark.callId&&state.frameId===bookmark.frameId)||null;
  return null;
}
function renderLocal(value){
  localValue=value;
  const frames=Array.isArray(value.frames)?value.frames:[];
  const observed=frames.map(localFrameState).filter(Boolean);
  states=[uploadState,...observed,...(callValue?callValue.frames:[])];
  localStatus.textContent=observed.length
    ? observed.length+" browser-local observations. Expires "+(value.expiresAt?timeLabel(value.expiresAt):"when this browser session ends")+"."
    : "No browser-local states observed yet.";
  renderStates();
  if(pendingBookmark&&pendingBookmark.kind==="local"){
    const found=findStateForBookmark(pendingBookmark);
    if(found){selectState(found,true);pendingBookmark=null;}
    else if(localLoaded){selectState(uploadState,true);pendingBookmark=null;stateStatus.textContent="That browser-local observation expired or is unavailable.";}
  }else if(!stateForKey(selectedKey))selectState(uploadState,true);
}
function renderCall(value,requestedFrame){
  if(!value||!uuid.test(value.callId||"")||!Array.isArray(value.frames))throw Error("The call API returned an invalid observation catalog.");
  activeCall=true;callInput.value=value.callId;
  const previousSelection=stateForKey(selectedKey);
  const frames=value.frames.map(frame=>callFrameState(frame,value.callId)).filter(Boolean);
  callValue={callId:value.callId,expiresAt:value.expiresAt,frames};
  states=[uploadState,...(localValue&&Array.isArray(localValue.frames)?localValue.frames.map(localFrameState).filter(Boolean):[]),...frames];
  renderStates();
  const desired=requestedFrame?frames.find(state=>state.frameId===requestedFrame):frames.find(state=>previousSelection&&state.key===previousSelection.key);
  if(previousSelection?.kind==="fixture")selectState(previousSelection,true);
  else if(desired)selectState(desired,true);
  else if(frames.length)selectState(frames[0],true);
  else selectState(uploadState,true);
  status.textContent=frames.length
    ? "Live access verified. "+frames.length+" API observations. Capture expires "+timeLabel(value.expiresAt)+"."
    : "No production API states captured. Unavailable stages stay unavailable.";
  return frames;
}
function failCall(error){
  activeCall=false;callValue=null;
  status.textContent=error.message;
  states=[uploadState,...(localValue&&Array.isArray(localValue.frames)?localValue.frames.map(localFrameState).filter(Boolean):[])];
  renderStates();
  if(selectedKey.startsWith("processing:")){selectState(uploadState,true);stateStatus.textContent="The live call observation is unavailable; showing the upload screen.";}
}
async function loadCall(id,requestedFrame){
  status.textContent="Checking live access and loading observed states…";
  try{
    const value=await request("start",{call_id:id});
    const frames=renderCall(value,requestedFrame);
    if(requestedFrame){
      if(frames.some(frame=>frame.frameId===requestedFrame))pendingBookmark=null;
      else{pendingBookmark=null;selectState(uploadState,true);stateStatus.textContent="That processing observation is no longer available.";}
    }
  }catch(error){failCall(error);}
}
async function refreshLocal(){
  if(pendingLocal||document.hidden)return;
  pendingLocal=true;
  try{const value=await request("local/catalog");localLoaded=true;renderLocal(value);}
  catch(error){localStatus.textContent=error.message;localLoaded=true;if(pendingBookmark&&pendingBookmark.kind==="local"){pendingBookmark=null;selectState(uploadState,true);stateStatus.textContent="That browser-local observation is expired or unavailable.";}}
  finally{pendingLocal=false;}
}
async function refreshCall(){
  if(!activeCall||pendingCall||document.hidden)return;
  pendingCall=true;
  try{renderCall(await request("catalog"));}
  catch(error){failCall(error);}
  finally{pendingCall=false;}
}
function readCallId(value){
  const input=value.trim();
  if(uuid.test(input))return input;
  try{
    const url=new URL(input,location.origin);
    const allowedOrigins=new Set([location.origin,"https://salesxray.authorityclosers.com","https://learner.authorityclosers.com"]);
    if(!allowedOrigins.has(url.origin)||url.searchParams.getAll("call").length!==1)return "";
    const id=url.searchParams.get("call");
    return uuid.test(id||"")?id:"";
  }catch{return "";}
}
document.getElementById("capture").addEventListener("submit",event=>{
  event.preventDefault();
  const id=readCallId(callInput.value);
  if(!id){status.textContent="Enter one valid saved call ID or Sales Xray call URL.";return;}
  void loadCall(id);
});
document.getElementById("reset").addEventListener("click",async()=>{
  try{
    await request("reset",{});activeCall=false;callValue=null;callInput.value="";
    states=[uploadState,...(localValue&&Array.isArray(localValue.frames)?localValue.frames.map(localFrameState).filter(Boolean):[])];
    status.textContent="Live call inspection cleared.";renderStates();selectState(uploadState,true);
  }catch(error){failCall(error);}
});
function moveSelection(direction){
  const sequence=selectedSequence();
  const index=sequence.findIndex(state=>state.key===selectedKey);
  const state=sequence[index+direction];
  if(state)selectState(state,false);
}
previous.addEventListener("click",()=>moveSelection(-1));
next.addEventListener("click",()=>moveSelection(1));
function setWidth(width,replace,updateBookmark=true){
  viewport.dataset.width=width;
  document.getElementById("desktop-width").setAttribute("aria-pressed",String(width==="desktop"));
  document.getElementById("mobile-width").setAttribute("aria-pressed",String(width==="mobile"));
  const current=stateForKey(selectedKey)||uploadState;
  if(updateBookmark)writeBookmark(current,replace);
}
document.getElementById("desktop-width").addEventListener("click",()=>setWidth("desktop",true));
document.getElementById("mobile-width").addEventListener("click",()=>setWidth("mobile",true));
document.getElementById("copy-url").addEventListener("click",async()=>{
  if(!currentAppUrl)return;
  try{
    if(navigator.clipboard&&navigator.clipboard.writeText)await navigator.clipboard.writeText(currentAppUrl.href);
    else{directUrl.focus();directUrl.select();document.execCommand("copy");}
    stateStatus.textContent="Direct app URL copied.";
  }catch{stateStatus.textContent="Copy was unavailable. Select the direct app URL field to copy it manually.";}
});
document.getElementById("fullscreen").addEventListener("click",async()=>{
  if(!currentAppUrl)return;
  try{
    if(document.fullscreenElement)await document.exitFullscreen();
    else if(canvas.requestFullscreen)await canvas.requestFullscreen();
    else window.open(currentAppUrl.href,"_blank","noopener,noreferrer");
  }catch{window.open(currentAppUrl.href,"_blank","noopener,noreferrer");}
});
function restoreBookmark(){
  const bookmark=parseBookmark();
  if(!bookmark){pendingBookmark=null;setWidth("desktop",true);selectState(uploadState,true);return;}
  setWidth(bookmark.width,true,false);
  pendingBookmark=bookmark;
  if(bookmark.kind==="processing"){
    callInput.value=bookmark.callId;
    void loadCall(bookmark.callId,bookmark.frameId);
  }else if(bookmark.kind==="fixture"){
    pendingBookmark=null;selectState(findStateForBookmark(bookmark),true);
  }else if(bookmark.kind==="upload"){
    pendingBookmark=null;selectState(uploadState,true);
  }else{
    const found=findStateForBookmark(bookmark);
    if(found){pendingBookmark=null;selectState(found,true);}
    else if(localLoaded){pendingBookmark=null;selectState(uploadState,true);stateStatus.textContent="That browser-local observation expired or is unavailable.";}
  }
}
window.addEventListener("popstate",restoreBookmark);
window.addEventListener("hashchange",restoreBookmark);
const initialBookmark=parseBookmark();
if(initialBookmark)setWidth(initialBookmark.width,true,false);
renderStates();
if(initialBookmark&&initialBookmark.kind==="processing"){
  pendingBookmark=initialBookmark;callInput.value=initialBookmark.callId;void loadCall(initialBookmark.callId,initialBookmark.frameId);
}else if(initialBookmark&&initialBookmark.kind==="fixture"){
  pendingBookmark=null;selectState(findStateForBookmark(initialBookmark),true);
}else if(initialBookmark&&initialBookmark.kind==="local")pendingBookmark=initialBookmark;
else{pendingBookmark=null;selectState(uploadState,true);}
void refreshLocal();
setInterval(()=>void refreshCall(),5000);
setInterval(()=>void refreshLocal(),5000);
`;
