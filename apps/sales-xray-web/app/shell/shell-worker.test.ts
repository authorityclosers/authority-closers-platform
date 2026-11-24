// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";

import {
  CACHE_PREFIX,
  OFF_KEY,
  inPhoneApp,
  readLocalSwitch,
  startWorker,
  workerUrl,
} from "./shell-worker";

// v1.96 device polish, lane P: offline after the first load showed Chrome's
// dino page. The worker that fixes it must never run in the phone apps and
// must always be easy to switch off.
const HERE = dirname(fileURLToPath(import.meta.url));

type FakeWin = Window & {
  registered: string[];
  unregistered: number;
  deleted: string[];
};

function fakeWindow({
  ua = "Mozilla/5.0 (Linux; Android 14; K) Chrome/131 Mobile",
  search = "",
  pathname = "/leads",
  bridge = false,
} = {}): FakeWin {
  const store = new Map<string, string>();
  const win = {
    registered: [] as string[],
    unregistered: 0,
    deleted: [] as string[],
    isSecureContext: true,
    location: {
      search,
      pathname,
      href: `https://app.test${pathname}${search}`,
      origin: "https://app.test",
    },
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    },
    performance: { getEntriesByType: () => [] },
    caches: {
      keys: async () => [`${CACHE_PREFIX}abc`, "someone-else"],
      delete: async (name: string) => {
        win.deleted.push(name);
        return true;
      },
    },
    navigator: {
      userAgent: ua,
      serviceWorker: {
        register: async (url: string) => {
          win.registered.push(url);
          return { active: { postMessage: () => undefined } };
        },
        getRegistrations: async () => [
          {
            active: { scriptURL: "https://app.test/sw.js?v=abc" },
            unregister: async () => {
              win.unregistered += 1;
              return true;
            },
          },
        ],
      },
    },
    ...(bridge ? { SXPhone: {} } : {}),
  };
  return win as unknown as FakeWin;
}

afterEach(() => vi.unstubAllEnvs());

it("registers the worker named by its release on the website", async () => {
  vi.stubEnv(
    "NEXT_PUBLIC_AC_RELEASE_ID",
    "0f3c2a9b1d4e5f60718293a4b5c6d7e8f9012345",
  );
  const win = fakeWindow();
  await startWorker(win, false);
  expect(win.registered).toEqual(["/sw.js?v=0f3c2a9b1d4e"]);
  expect(workerUrl(null)).toBe("/sw.js?v=dev");
});

it("never runs in the phone apps, and removes one found there", async () => {
  for (const win of [
    fakeWindow({
      ua: "Mozilla/5.0 (Linux; Android 14) Chrome/131 SalesXrayApp/1.0.99",
    }),
    fakeWindow({ bridge: true }),
  ]) {
    expect(inPhoneApp(win)).toBe(true);
    await startWorker(win, false);
    expect(win.registered).toEqual([]);
    expect(win.unregistered).toBe(1);
    expect(win.deleted).toEqual([`${CACHE_PREFIX}abc`]);
  }
});

it("switches off for everyone with the server's flag, and per browser with ?sw=off until ?sw=on", async () => {
  const everyone = fakeWindow();
  await startWorker(everyone, true);
  expect(everyone.registered).toEqual([]);
  expect(everyone.unregistered).toBe(1);

  const one = fakeWindow({ search: "?sw=off" });
  expect(readLocalSwitch(one)).toBe(true);
  expect(one.localStorage.getItem(OFF_KEY)).toBe("1");
  (one.location as { search: string }).search = "";
  expect(readLocalSwitch(one)).toBe(true);
  (one.location as { search: string }).search = "?sw=on";
  expect(readLocalSwitch(one)).toBe(false);
  expect(readLocalSwitch(fakeWindow({ pathname: "/sw-off" }))).toBe(true);
});

it("keeps pages and the API out of the worker: only build files and its own offline screen", () => {
  const sw = readFileSync(join(HERE, "../../public/sw.js"), "utf8");
  // Pages: network first, never put in the cache.
  expect(sw).toContain('request.mode === "navigate"');
  expect(sw).not.toMatch(/cache\.put\(\s*event\.request/);
  // Only content-hashed build files sent as immutable are kept.
  expect(sw).toContain('url.pathname.startsWith("/_next/static/")');
  expect(sw).toMatch(/immutable/);
  // Sign-in and the API are never answered, not even offline.
  for (const path of ["__as", "v1", "auth", "login", "logout", "oauth"])
    expect(sw).toContain(path);
  expect(sw).toContain('request.method !== "GET"');
  expect(sw).toContain('request.headers.has("range")');
  // Each release clears the earlier releases' files.
  expect(sw).toMatch(/name\.startsWith\(PREFIX\) && name !== CACHE/);
  const offline = readFileSync(join(HERE, "../../public/offline.html"), "utf8");
  expect(offline).toContain("No internet");
  expect(offline).toContain("Try again");
  expect(offline).not.toMatch(/<script[^>]+src=/);
});
