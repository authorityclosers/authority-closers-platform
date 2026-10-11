/**
 * Early reads (owner, 11 Oct: pages load fast, no client waterfalls).
 *
 * A full page load used to wait for the JavaScript, then the session check
 * (two reads, one after the other), then the page's own reads: three round
 * trips after the app had already started. A small inline script now starts
 * those GETs while the HTML is still being read, and the app's normal read
 * helpers take the answers instead of asking again.
 *
 * Rules that keep this safe:
 * - GETs only, fixed paths per page, same-origin with the browser's own
 *   cookies (exactly what the page would send a moment later);
 * - an answer is used within EARLY_READ_TTL_MS of the page load, and by the
 *   first reader that is not cancelled (React's development double mount
 *   cancels the first one, which leaves the answer for the second);
 * - every early answer is dropped when the workspace selection changes, so
 *   no page reads data fetched for another workspace.
 *
 * Nothing here decides access, progress or payment; the server answers each
 * read as usual.
 */

export const EARLY_READ_TTL_MS = 10_000;

/**
 * Conversation reads start early only after this tab has seen the selected
 * workspace with Sales Xray on (sessionStorage). A first visit, a switch to
 * another workspace, signing out, or a workspace without Sales Xray: only
 * the session reads start early, and the page asks for the rest itself.
 */
export const EARLY_CONVERSATION_KEY = "sx.early.conversation";

const EARLY_SESSION_ONLY = (url: string) => url.startsWith("/v1/me/");

/** Remember (or forget) that conversation reads may start early here. */
export function allowEarlyConversationReads(allowed: boolean) {
  try {
    if (allowed) window.sessionStorage.setItem(EARLY_CONVERSATION_KEY, "1");
    else window.sessionStorage.removeItem(EARLY_CONVERSATION_KEY);
  } catch {
    // Storage refused: the page simply reads as before.
  }
}

const ACQUISITION = "/v1/conversation/acquisition";
const SESSION = ["/v1/me/workspaces", "/v1/me/sales-xray-workspaces"];
const STUDIO = [
  `${ACQUISITION}/entry`,
  `${ACQUISITION}/upload-policy`,
  `${ACQUISITION}/session`,
  `${ACQUISITION}/availability`,
];

/** The reads each page makes as soon as it mounts (exact URLs). */
export const EARLY_READS: Readonly<Record<string, readonly string[]>> = {
  "/dashboard": [
    ...SESSION,
    `${ACQUISITION}/submissions/summary`,
    `${ACQUISITION}/activity`,
    `${ACQUISITION}/session`,
    `${ACQUISITION}/submissions?include_owners=true`,
  ],
  "/analysis/calls": [
    ...SESSION,
    `${ACQUISITION}/submissions?include_owners=true`,
  ],
  "/analysis/new": [...SESSION, ...STUDIO],
  "/organisation": [...SESSION],
  "/account": [...SESSION],
  "/prospects": [...SESSION],
};

/** A saved call: the session, the studio's entry and allowance, the call. */
const CALL_PAGE = /^\/analysis\/calls\/([0-9a-f-]{36})$/i;
const CALL_READS = [
  ...SESSION,
  `${ACQUISITION}/entry`,
  `${ACQUISITION}/session`,
];

/** The early reads for an address (trailing slash ignored), or none. */
export function earlyReadsFor(pathname: string): readonly string[] {
  const route = pathname.replace(/\/$/, "") || "/";
  const call = CALL_PAGE.exec(route)?.[1];
  if (call)
    return [...CALL_READS, `${ACQUISITION}/submissions/${call.toLowerCase()}`];
  return EARLY_READS[route] ?? [];
}

type Early = { at: number; p: Promise<Response | null> };
type EarlyStore = Record<string, Early>;
type EarlyWindow = Window & { __sxEarly?: EarlyStore };

/**
 * The inline script for the root layout: it starts this page's reads and
 * keeps the pending answers on window.__sxEarly. Failures are swallowed;
 * the app then simply reads as before.
 */
export function earlyReadsScript(): string {
  const table = JSON.stringify(EARLY_READS);
  const call = JSON.stringify(CALL_PAGE.source);
  const callReads = JSON.stringify(CALL_READS);
  const acquisition = JSON.stringify(ACQUISITION);
  const key = JSON.stringify(EARLY_CONVERSATION_KEY);
  return `(function(){try{if(typeof fetch!=="function")return;var t=${table},r=location.pathname.replace(/\\/$/,"")||"/",m=new RegExp(${call},"i").exec(r),l=m?${callReads}.concat([${acquisition}+"/submissions/"+m[1].toLowerCase()]):t[r];if(!l||!l.length)return;var ok=false;try{ok=sessionStorage.getItem(${key})==="1"}catch(e){}if(!ok)l=l.filter(function(u){return u.indexOf("/v1/me/")===0});var s=window.__sxEarly={},a=Date.now();l.forEach(function(u){if(s[u])return;s[u]={at:a,p:fetch(u,{method:"GET",credentials:"same-origin",cache:"no-store",redirect:"error",headers:{accept:"application/json"}}).catch(function(){return null})}})}catch(e){}})();`;
}

function store(): EarlyStore | null {
  if (typeof window === "undefined") return null;
  return (window as EarlyWindow).__sxEarly ?? null;
}

/**
 * The early answer for a GET of this URL, as a fresh copy, or null (none,
 * expired, not a plain GET, or already cancelled). The caller still owns
 * every check it makes on a response.
 */
export function takeEarlyRead(
  url: string,
  init: RequestInit = {},
): Promise<Response | null> | null {
  const early = store()?.[url];
  if (!early) return null;
  if ((init.method ?? "GET").toUpperCase() !== "GET" || init.body) return null;
  if (Date.now() - early.at > EARLY_READ_TTL_MS) {
    delete store()?.[url];
    return null;
  }
  if (init.signal?.aborted) return null;
  return early.p.then((response) => {
    // A copy each time: the original stays unread for a second reader.
    try {
      return response && !response.bodyUsed ? response.clone() : null;
    } catch {
      return null;
    }
  });
}

/** The reader got its answer (not cancelled): later reads ask the server. */
export function settleEarlyRead(url: string) {
  const early = store();
  if (early) delete early[url];
}

/**
 * Forget every early answer: the workspace selection or the person changed
 * (a sign-in on the page, a sign-out), so none of them is current any more.
 */
export function dropEarlyReads() {
  const early = store();
  if (early) for (const url of Object.keys(early)) delete early[url];
}

/** Only the session reads (for tests and the script's own rule). */
export const sessionOnly = (urls: readonly string[]) =>
  urls.filter(EARLY_SESSION_ONLY);

/**
 * fetch() for a GET, served from the early answer when there is one. The
 * early answer is settled only for a reader that was not cancelled.
 */
export async function earlyFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const early = takeEarlyRead(url, init);
  if (early) {
    const response = await early;
    if (init.signal?.aborted)
      throw new DOMException("The read was cancelled.", "AbortError");
    if (response) {
      settleEarlyRead(url);
      return response;
    }
    settleEarlyRead(url);
  }
  return fetch(url, init);
}
