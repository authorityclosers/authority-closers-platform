/**
 * The website line itself (public/sx.js), run as a site runs it: what it sends when a
 * visitor arriving from an ad sends a lead form, and what it never sends.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// vitest runs in apps/sales-xray-web.
const SOURCE = readFileSync(resolve(process.cwd(), "public/sx.js"), "utf8");
const KEY = "sxw_fictionalkeyfictionalkey0001";

type Sent = { url: string; body: Record<string, unknown> };
let sent: Sent[];
// Each test loads the line afresh; the document stays, so the listeners the last load
// added are taken off again (a page loads the line once).
type Added = Parameters<Document["addEventListener"]>;
let added: Added[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify({ ok: true, site: "active" }), {
        status: url.endsWith("/lead") ? 202 : 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  localStorage.clear();
  document.cookie = "_fbp=fb.1.1730280000000.1234567890; path=/";
  window.history.replaceState(
    null,
    "",
    "/site-visit?utm_source=google&utm_medium=cpc&utm_campaign=Diwali&gclid=Cj0KCQ-fictional",
  );
  document.head.innerHTML = `<meta name="generator" content="WordPress 6.9"><script src="https://sx.example/sx.js" data-key="${KEY}" async></script>`;
  // A step-by-step form as some sites build it: the answers sit in hidden fields.
  document.body.innerHTML = `
    <form id="lead" method="post" action="/thank-you" name="Site visit" novalidate>
      <input type="hidden" name="name" value="Asha Fictional">
      <input type="hidden" name="phone" value="98765 00041">
      <input type="hidden" name="intent" value="Book a site visit">
      <input type="hidden" name="_wpnonce" value="abc123">
      <input type="hidden" name="utm_source" value="google">
      <input type="hidden" name="token" value="${"x".repeat(160)}">
      <label for="e">Email</label><input id="e" name="your-email" type="email" value="asha@fictional.example.com">
      <label for="p">Password</label><input id="p" name="pw" type="text" value="">
      <label for="c">Card number</label><input id="c" name="card" value="4111 1111 1111 1111">
      <input name="website" type="text" tabindex="-1" autocomplete="off" value="">
      <label for="m">Message</label><textarea id="m" name="message">Call me after 6</textarea>
      <label><input type="checkbox" name="wa" checked> Send me updates on WhatsApp</label>
      <button type="submit">Book</button>
    </form>
    <form role="search"><input name="s" value="homes"></form>`;
  delete (window as { __salesXray?: unknown }).__salesXray;
  const listen = Document.prototype.addEventListener;
  document.addEventListener = function (this: Document, ...args: Added) {
    added.push(args);
    listen.apply(this, args);
  } as Document["addEventListener"];
  new Function(SOURCE)();
  Reflect.deleteProperty(document, "addEventListener");
});

afterEach(() => {
  for (const [type, listener, options] of added)
    document.removeEventListener(type, listener, options);
  added = [];
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.cookie = "_fbp=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

/** Let the sends' answers arrive (each is a few promise steps). */
const settle = async () => {
  await vi.advanceTimersByTimeAsync(10);
  for (let step = 0; step < 10; step += 1) await Promise.resolve();
};

const send = (form: HTMLFormElement) => {
  document.dispatchEvent(new KeyboardEvent("keydown"));
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
};

it("says hello once with the page's lead forms and its builder", async () => {
  await vi.advanceTimersByTimeAsync(1000);
  const hellos = sent.filter((item) => item.url.endsWith("/site/hello"));
  expect(hellos).toHaveLength(1);
  expect(hellos[0].url).toBe("https://sx.example/v1/lead-desk/site/hello");
  expect(hellos[0].body).toMatchObject({ k: KEY, f: 1, p: "wordpress" });
  // The page's address only: never its query or fragment.
  expect(hellos[0].body.u).toBe(`${location.origin}/site-visit`);
});

it("sends a lead form's answers with where the visit came from, and nothing secret", async () => {
  vi.advanceTimersByTime(4000);
  send(document.getElementById("lead") as HTMLFormElement);
  await settle();
  const leads = sent.filter((item) => item.url.endsWith("/site/lead"));
  expect(leads).toHaveLength(1);
  const body = leads[0].body as {
    k: string;
    fields: { k: string; v: string; r: string | null }[];
    a: { last: Record<string, string> };
    hp: boolean;
    it: number;
    form: string;
  };
  expect(body.k).toBe(KEY);
  expect(body.form).toBe("Site visit");
  expect(body.fields).toEqual([
    { k: "Name", v: "Asha Fictional", r: "name" },
    { k: "Phone", v: "98765 00041", r: "phone" },
    { k: "Intent", v: "Book a site visit", r: null },
    { k: "Email", v: "asha@fictional.example.com", r: "email" },
    { k: "Message", v: "Call me after 6", r: "message" },
    // A ticked box reads as yes, so a WhatsApp consent question matches it.
    { k: "Send me updates on WhatsApp", v: "Yes", r: null },
  ]);
  expect(body.a.last).toMatchObject({
    utm_source: "google",
    utm_campaign: "Diwali",
    gclid: "Cj0KCQ-fictional",
    fbp: "fb.1.1730280000000.1234567890",
  });
  expect(body.hp).toBe(false);
  expect(body.it).toBeGreaterThan(0);
  // Kept in the browser until Sales X-Ray has it; gone once it answered.
  expect(localStorage.getItem("sx_q")).toBeNull();
});

it("marks a filled honeypot, skips search forms, and sends one press once", async () => {
  const form = document.getElementById("lead") as HTMLFormElement;
  (form.elements.namedItem("website") as HTMLInputElement).value =
    "spam.example";
  send(form);
  send(form);
  send(document.querySelector('form[role="search"]') as HTMLFormElement);
  await settle();
  const leads = sent.filter((item) => item.url.endsWith("/site/lead"));
  expect(leads).toHaveLength(1);
  expect(leads[0].body.hp).toBe(true);
});

it("takes a lead from a form that isn't a <form>", async () => {
  (window as unknown as { sx: (c: string, d: object) => void }).sx("lead", {
    name: "Ravi Example",
    mobile: "91234 56780",
    otp: "123456",
  });
  await settle();
  const lead = sent.find((item) => item.url.endsWith("/site/lead"));
  expect(lead?.body.fields).toEqual([
    { k: "Name", v: "Ravi Example", r: "name" },
    { k: "Mobile", v: "91234 56780", r: "phone" },
  ]);
});
