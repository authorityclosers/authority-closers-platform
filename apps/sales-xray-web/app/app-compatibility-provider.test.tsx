import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  AppCompatibilityProvider,
  FeatureGate,
  PLAY_LISTING,
  useFeatureEnabled,
} from "./app-compatibility-provider";
import { type AppConfig, REMIND_AFTER_MS } from "./app-compatibility";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const config: AppConfig = {
  min_app_version: { android: "1.2.0", ios: "0.0.0", desktop: "0.0.0" },
  recommended_app_version: {
    android: "1.10.0",
    ios: "0.0.0",
    desktop: "0.0.0",
  },
  features_off: [],
};
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function Probe() {
  return <span>{useFeatureEnabled("clarity") ? "enabled" : "disabled"}</span>;
}
async function mount(
  value: AppConfig = config,
  ua = "Android SalesXrayApp/1.0.0",
) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => value }),
  );
  await act(async () =>
    root.render(
      <AppCompatibilityProvider>
        <p>Workspace</p>
        <Probe />
        <FeatureGate feature="clarity">
          <p>Clarity feature</p>
        </FeatureGate>
      </AppCompatibilityProvider>,
    ),
  );
}
it("blocks below minimum without dismiss, even with a held reminder", async () => {
  localStorage.setItem(
    "sx-app-update-remind-after",
    String(Date.now() + REMIND_AFTER_MS),
  );
  await mount();
  expect(host.querySelector("h1")?.textContent).toBe("Update Sales X-Ray");
  expect(host.textContent).not.toContain("Workspace");
  expect(host.textContent).not.toContain("Not now");
  expect(host.querySelector("a")?.getAttribute("href")).toBe(PLAY_LISTING);
  expect(fetch).toHaveBeenCalledWith(
    "/v1/app/config",
    expect.objectContaining({ credentials: "omit" }),
  );
});
it("defers a recommended update for three days, including remount", async () => {
  await mount(config, "SalesXrayApp/1.2.0");
  const later = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Not now",
  );
  expect(later).toBeTruthy();
  await act(async () => later!.click());
  expect(host.textContent).toContain("Workspace");
  const until = Number(localStorage.getItem("sx-app-update-remind-after"));
  expect(until - Date.now()).toBeGreaterThan(REMIND_AFTER_MS - 1000);
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount(config, "SalesXrayApp/1.2.0");
  expect(host.textContent).toContain("Workspace");
  expect(host.textContent).not.toContain("Not now");
});
it("leaves browsers usable and switches a real feature off through the hook", async () => {
  await mount(
    { ...config, features_off: ["clarity"] },
    "Mozilla/5.0 Chrome/140",
  );
  expect(host.textContent).toContain("disabled");
  expect(host.textContent).toContain("Workspace");
  expect(host.textContent).not.toContain("Clarity feature");
});
it("fails open when config cannot be fetched", async () => {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("SalesXrayApp/1.0.0");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await act(async () =>
    root.render(
      <AppCompatibilityProvider>
        <p>Workspace</p>
      </AppCompatibilityProvider>,
    ),
  );
  expect(host.textContent).toContain("Workspace");
  expect(host.querySelector("h1")).toBeNull();
});
it("fails open on invalid server config", async () => {
  await mount({ ...config, features_off: ["unknown"] } as unknown as AppConfig);
  expect(host.textContent).toContain("Workspace");
});
it("refreshes remote feature switches on focus", async () => {
  await mount(config, "Mozilla/5.0");
  expect(host.textContent).toContain("Clarity feature");
  vi.mocked(fetch).mockResolvedValue({
    ok: true,
    json: async () => ({ ...config, features_off: ["clarity"] }),
  } as Response);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(host.textContent).not.toContain("Clarity feature");
});
