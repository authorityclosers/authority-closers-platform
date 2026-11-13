import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const path = vi.hoisted(() => ({ value: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => path.value }));
vi.mock("../app-session", () => ({
  isShellRoute: (pathname: string | null) => pathname === "/dashboard",
}));

import {
  GetAppSheet,
  SETTLED_KEY,
  SNOOZE_KEY,
  forgetTesterRead,
} from "./get-app-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 13 Nov 2026: a signed-in tester on Android's browser gets a big
// "Get the app" sheet with Play's two steps; never inside the app itself.
const ANDROID = "Mozilla/5.0 (Linux; Android 14; K) Chrome/130 Mobile";
const IN_APP = `${ANDROID} SalesXrayApp/1.0.99`;
let root: Root;
let host: HTMLDivElement;
const agent = Object.getOwnPropertyDescriptor(Navigator.prototype, "userAgent");

function as(userAgent: string) {
  Object.defineProperty(navigator, "userAgent", {
    value: userAgent,
    configurable: true,
  });
}

beforeEach(() => {
  forgetTesterRead();
  localStorage.clear();
  sessionStorage.clear();
  path.value = "/dashboard";
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  if (agent) Object.defineProperty(Navigator.prototype, "userAgent", agent);
  delete (navigator as { userAgent?: string }).userAgent;
});

const answer = (state: string) =>
  vi.fn(
    async () =>
      new Response(JSON.stringify({ state, email: "ravi.tester@gmail.com" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );

const sheetLinks = () =>
  [...document.querySelectorAll<HTMLAnchorElement>("a[data-step]")].map(
    (link) => link.getAttribute("href"),
  );

it("opens Play's two steps for a ready tester on an Android browser, and Not now snoozes it", async () => {
  as(ANDROID);
  const fetcher = answer("ready");
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<GetAppSheet />));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain("Get the Sales X-Ray app");
  expect(sheetLinks()).toEqual([
    "https://play.google.com/apps/testing/com.authorityclosers.salesxray",
    "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray",
  ]);
  // A ready tester isn't settled: the sheet may come back after its snooze.
  expect(sessionStorage.getItem(SETTLED_KEY)).toBeNull();
  await act(async () => {
    [...document.querySelectorAll("button")]
      .find((button) => button.textContent === "Not now")!
      .click();
  });
  expect(Number(localStorage.getItem(SNOOZE_KEY))).toBeGreaterThan(Date.now());
});

it("stays away inside the app, while snoozed, off the app's pages and for anyone not ready", async () => {
  const fetcher = answer("ready");
  vi.stubGlobal("fetch", fetcher);
  as(IN_APP);
  await act(async () => root.render(<GetAppSheet />));
  expect(fetcher).not.toHaveBeenCalled();

  as(ANDROID);
  localStorage.setItem(SNOOZE_KEY, String(Date.now() + 60_000));
  await act(async () => root.render(<GetAppSheet key="snoozed" />));
  expect(fetcher).not.toHaveBeenCalled();

  localStorage.clear();
  path.value = "/testers";
  await act(async () => root.render(<GetAppSheet key="testers" />));
  expect(fetcher).not.toHaveBeenCalled();

  path.value = "/dashboard";
  const waiting = answer("waiting");
  vi.stubGlobal("fetch", waiting);
  await act(async () => root.render(<GetAppSheet key="waiting" />));
  expect(waiting).toHaveBeenCalledTimes(1);
  expect(sheetLinks()).toEqual([]);
  // Not ready: this tab doesn't ask again on the next page load.
  expect(sessionStorage.getItem(SETTLED_KEY)).toBe("1");
  forgetTesterRead();
  await act(async () => root.render(<GetAppSheet key="again" />));
  expect(waiting).toHaveBeenCalledTimes(1);
});

it("asks once when React runs the effect twice, and still opens", async () => {
  as(ANDROID);
  const fetcher = answer("ready");
  vi.stubGlobal("fetch", fetcher);
  const { StrictMode } = await import("react");
  await act(async () =>
    root.render(
      <StrictMode>
        <GetAppSheet />
      </StrictMode>,
    ),
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain("Get the Sales X-Ray app");
});
