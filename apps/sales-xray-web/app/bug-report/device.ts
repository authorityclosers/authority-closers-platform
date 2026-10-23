/**
 * The app, build and device a bug report came from: what the team needs to
 * reproduce it, nothing personal. The server keeps only these fields
 * (ac_platform/bug_reports/scrub.py) and adds its own release.
 */

import { isAppUserAgent } from "../in-app";
import { inPhoneApp, phoneStatus } from "../leads/native-phone";

export type ReportContext = {
  app: {
    channel: "web" | "android";
    release?: string;
    native_version?: string;
  };
  device: {
    os?: string;
    browser?: string;
    model?: string;
    viewport: string;
    screen?: string;
    pixel_ratio?: number;
    mobile?: boolean;
    touch?: boolean;
    online?: boolean;
    standalone?: boolean;
    language?: string;
    timezone?: string;
    theme?: "light" | "dark";
    connection?: string;
    memory_gb?: number;
  };
};

type UserAgentData = {
  mobile?: boolean;
  getHighEntropyValues?: (
    hints: string[],
  ) => Promise<{ model?: string; platformVersion?: string }>;
};

/** "Android 14", "iOS 18.2", "Windows", "macOS" or "Linux" from a user agent. */
export function osFrom(userAgent: string): string | undefined {
  const android = /Android (\d+(?:\.\d+)?)/.exec(userAgent);
  if (android) return `Android ${android[1]}`;
  const ios = /(?:iPhone|iPad|iPod).*? OS (\d+)_(\d+)/.exec(userAgent);
  if (ios) return `iOS ${ios[1]}.${ios[2]}`;
  if (/Windows/.test(userAgent)) return "Windows";
  if (/Mac OS X/.test(userAgent)) return "macOS";
  if (/Linux/.test(userAgent)) return "Linux";
  return undefined;
}

/** "Chrome 141", "Edge 141", "Firefox 132", "Safari 18" or "Android WebView 141". */
export function browserFrom(userAgent: string): string | undefined {
  const pick = (pattern: RegExp, name: string) => {
    const found = pattern.exec(userAgent);
    return found ? `${name} ${found[1]}` : undefined;
  };
  if (/; wv\)/.test(userAgent) || isAppUserAgent(userAgent)) {
    return pick(/Chrome\/(\d+)/, "Android WebView");
  }
  return (
    pick(/Edg\/(\d+)/, "Edge") ??
    pick(/SamsungBrowser\/(\d+)/, "Samsung Internet") ??
    pick(/Firefox\/(\d+)/, "Firefox") ??
    pick(/Chrome\/(\d+)/, "Chrome") ??
    pick(/Version\/(\d+).*Safari/, "Safari")
  );
}

let release: Promise<string | undefined> | null = null;

/** The web app's release, from its own health route (cached for the page). */
function webRelease(): Promise<string | undefined> {
  release ??= fetch("/health", { cache: "no-store", credentials: "omit" })
    .then((response) => (response.ok ? response.json() : null))
    .then((body: { release_id?: unknown } | null) =>
      typeof body?.release_id === "string" &&
      /^[A-Za-z0-9._-]{1,40}$/.test(body.release_id)
        ? body.release_id
        : undefined,
    )
    .catch(() => undefined);
  return release;
}

export async function reportContext(): Promise<ReportContext> {
  const userAgent = navigator.userAgent;
  const nav = navigator as Navigator & {
    userAgentData?: UserAgentData;
    connection?: { effectiveType?: string };
    deviceMemory?: number;
  };
  const inApp = inPhoneApp() || isAppUserAgent(userAgent);
  const [releaseId, phone, hints] = await Promise.all([
    webRelease(),
    inApp ? phoneStatus() : Promise.resolve(null),
    nav.userAgentData?.getHighEntropyValues
      ? nav.userAgentData
          .getHighEntropyValues(["model", "platformVersion"])
          .catch(() => null)
      : Promise.resolve(null),
  ]);
  const media = (query: string) => window.matchMedia?.(query).matches === true;
  const theme = document.documentElement.dataset.theme;
  return {
    app: {
      channel: inApp ? "android" : "web",
      ...(releaseId ? { release: releaseId } : {}),
      ...(phone?.version ? { native_version: phone.version } : {}),
    },
    device: {
      os: osFrom(userAgent),
      browser: browserFrom(userAgent),
      ...(hints?.model ? { model: hints.model } : {}),
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      screen: `${window.screen.width}x${window.screen.height}`,
      pixel_ratio: Math.round(window.devicePixelRatio * 100) / 100,
      mobile: nav.userAgentData?.mobile ?? /Mobi|Android/.test(userAgent),
      touch: media("(pointer: coarse)"),
      online: navigator.onLine,
      standalone: media("(display-mode: standalone)"),
      language: navigator.language,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      theme:
        theme === "dark" || theme === "light"
          ? theme
          : media("(prefers-color-scheme: dark)")
            ? "dark"
            : "light",
      ...(nav.connection?.effectiveType
        ? { connection: nav.connection.effectiveType }
        : {}),
      ...(typeof nav.deviceMemory === "number"
        ? { memory_gb: nav.deviceMemory }
        : {}),
    },
  };
}
