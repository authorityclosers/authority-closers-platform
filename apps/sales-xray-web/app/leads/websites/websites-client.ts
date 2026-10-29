/**
 * The Websites card's API (/v1/lead-desk/websites, lead_desk/websites_http.py): the
 * organisation's one line of script, and each site and landing page it is on.
 */

import { LeadsError } from "../leads-client";

const API = "/v1/lead-desk/websites";

export type WebsitePage = {
  path: string;
  title: string | null;
  views: number;
  forms: number;
  fills: number;
  leads: number;
  blocked: number;
  /** Form fills per view, 0 to 1; null without views. */
  rate: number | null;
  last_day: string;
};

export type WebsiteStatus = "active" | "paused";

export type Website = {
  site_id: string;
  host: string;
  label: string;
  status: WebsiteStatus;
  platform: string | null;
  added: "person" | "seen";
  first_seen_at: string | null;
  last_seen_at: string | null;
  last_page: string | null;
  last_lead_at: string | null;
  /** A computer's own address or a test name: its leads are test data. */
  test: boolean;
  views: number;
  forms: number;
  fills: number;
  leads: number;
  blocked: number;
  rate: number | null;
  pages: WebsitePage[];
};

export type Websites = {
  on: boolean;
  /** Null until someone starts (Add website): a read never makes the key. */
  key: string | null;
  script_url: string;
  snippet: string | null;
  period_days: number;
  sites: Website[];
  views: number;
  leads: number;
  rate: number | null;
  now: string;
};

async function call<T>(path = "", init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: {
        accept: "application/json",
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new LeadsError("Sales X-Ray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

/** The card's answer, checked for the few fields it draws from; anything else is no answer. */
export function websitesFrom(raw: unknown): Websites {
  const body = raw as Partial<Websites> | null;
  if (
    !body ||
    !Array.isArray(body.sites) ||
    typeof body.script_url !== "string" ||
    typeof body.now !== "string" ||
    body.sites.some(
      (site) =>
        !site ||
        typeof site.site_id !== "string" ||
        typeof site.host !== "string" ||
        !Array.isArray(site.pages),
    )
  )
    throw new LeadsError("Websites didn't load. Try again.", 0);
  return body as Websites;
}

const websitesCall = async (path = "", init: RequestInit = {}) =>
  websitesFrom(await call<unknown>(path, init));

export const readWebsites = () => websitesCall();
export const startWebsites = () => websitesCall("/start", { method: "POST" });
export const addWebsite = (address: string) =>
  websitesCall("", { method: "POST", body: JSON.stringify({ address }) });
export const setWebsiteStatus = (siteId: string, status: WebsiteStatus) =>
  websitesCall(`/${encodeURIComponent(siteId)}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
export const removeWebsite = (siteId: string) =>
  websitesCall(`/${encodeURIComponent(siteId)}`, { method: "DELETE" });
export const newWebsiteKey = () => websitesCall("/key", { method: "POST" });
export const sendWebsiteTestLead = (siteId: string) =>
  call<{ lead_id: string | null }>(`/${encodeURIComponent(siteId)}/test`, {
    method: "POST",
  });

/** "3.2%" from a 0-1 share; a dash when there were no visits. */
export function percent(rate: number | null): string {
  if (rate === null) return "–";
  const value = rate * 100;
  return `${value >= 10 || value === 0 ? Math.round(value) : value.toFixed(1)}%`;
}

/** "10:42" today, "Yesterday 10:42", else "28 Oct". */
export function seenAt(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  });
  const days = Math.floor(
    (new Date(now.toDateString()).getTime() -
      new Date(at.toDateString()).getTime()) /
      86_400_000,
  );
  if (days <= 0) return time;
  if (days === 1) return `Yesterday ${time}`;
  return at.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export const PLATFORM_NAMES: Record<string, string> = {
  wordpress: "WordPress",
  elementor: "Elementor",
  webflow: "Webflow",
  framer: "Framer",
  wix: "Wix",
  squarespace: "Squarespace",
  shopify: "Shopify",
  hubspot: "HubSpot",
  nextjs: "Next.js",
};

/** One plain line under a site's name: its state, when it was last seen, its forms. */
export function siteLine(site: Website, now: Date = new Date()): string {
  if (site.status === "paused") return "Paused · its forms add no leads";
  if (!site.last_seen_at) return "Waiting for the first visit";
  const forms =
    site.forms === 0
      ? "no lead forms seen yet"
      : `${site.forms} lead form${site.forms === 1 ? "" : "s"}`;
  return `Live · seen ${seenAt(site.last_seen_at, now)} · ${forms}`;
}

/** Where to paste the line on each builder, in a few short steps. */
export const PASTE_STEPS: { id: string; name: string; steps: string[] }[] = [
  {
    id: "wordpress",
    name: "WordPress",
    steps: [
      "Plugins → Add new → install and turn on WPCode.",
      "Code Snippets → Header & Footer.",
      "Paste the line into Header, then Save.",
    ],
  },
  {
    id: "elementor",
    name: "Elementor",
    steps: [
      "Elementor → Custom Code → Add new.",
      "Paste the line, set Location to <head>.",
      "Publish, on the entire site.",
    ],
  },
  {
    id: "webflow",
    name: "Webflow",
    steps: [
      "Site settings → Custom code.",
      "Paste the line into Head code, then Save.",
      "Publish the site.",
    ],
  },
  {
    id: "framer",
    name: "Framer",
    steps: [
      "Site settings → General → Custom code.",
      "Paste the line into End of <head> tag.",
      "Publish.",
    ],
  },
  {
    id: "wix",
    name: "Wix",
    steps: [
      "Settings → Custom code → Add custom code.",
      "Paste the line, choose All pages and Head.",
      "Apply.",
    ],
  },
  {
    id: "shopify",
    name: "Shopify",
    steps: [
      "Online Store → Themes → ⋯ → Edit code.",
      "Open theme.liquid and paste the line just before </head>.",
      "Save.",
    ],
  },
  {
    id: "other",
    name: "Other",
    steps: [
      "Paste the line just before </head> on every page.",
      "If your site has one shared header, once there is enough.",
    ],
  },
];

/** An email a business owner sends whoever runs the site. */
export function emailForWebPerson(snippet: string): string {
  const body = [
    "Hi,",
    "",
    "Please add this one line to our website, just before </head> on every page (the shared header is enough):",
    "",
    snippet,
    "",
    "It sends every enquiry form to our CRM (Sales X-Ray) with the page and the ad it came from. The forms keep working as they do now.",
    "",
    "Thank you",
  ].join("\n");
  return `mailto:?subject=${encodeURIComponent("One line for our website")}&body=${encodeURIComponent(body)}`;
}
