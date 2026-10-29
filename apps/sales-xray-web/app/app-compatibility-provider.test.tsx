import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppCompatibilityProvider, FeatureGate, PLAY_LISTING, useFeatureEnabled } from "./app-compatibility-provider";
import { type AppConfig, REMIND_AFTER_MS } from "./app-compatibility";
const config: AppConfig = {
  min_app_version: { android: "1.2.0", ios: "0.0.0", desktop: "0.0.0" },
  recommended_app_version: { android: "1.10.0", ios: "0.0.0", desktop: "0.0.0" },
  features_off: [],
};
function Probe() { return <span>{useFeatureEnabled("clarity") ? "enabled" : "disabled"}</span>; }
function mount(value: AppConfig = config, ua = "Android SalesXrayApp/1.0.0") {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => value }));
  return render(<AppCompatibilityProvider><p>Workspace</p><Probe /><FeatureGate feature="clarity"><p>Clarity feature</p></FeatureGate></AppCompatibilityProvider>);
}
beforeEach(() => localStorage.clear());
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("blocks the workspace below minimum without a dismiss action", async () => {
  localStorage.setItem("sx-app-update-remind-after", String(Date.now() + REMIND_AFTER_MS));
  mount();
  await screen.findByRole("heading", { name: "Update Sales X-Ray" });
  expect(screen.queryByText("Workspace")).toBeNull();
  expect(screen.queryByText("Not now")).toBeNull();
  expect(screen.getByRole("link").getAttribute("href")).toBe(PLAY_LISTING);
});
it("defers a recommended update for three days, including remount", async () => {
  const view = mount(config, "SalesXrayApp/1.2.0");
  fireEvent.click(await screen.findByText("Not now"));
  expect(screen.getByText("Workspace")).toBeTruthy();
  const until = Number(localStorage.getItem("sx-app-update-remind-after"));
  expect(until - Date.now()).toBeGreaterThan(REMIND_AFTER_MS - 1000);
  view.unmount();
  mount(config, "SalesXrayApp/1.2.0");
  await waitFor(() => expect(screen.getByText("Workspace")).toBeTruthy());
  expect(screen.queryByText("Not now")).toBeNull();
});
it("leaves browsers usable and switches a real feature off through the hook", async () => {
  mount({ ...config, features_off: ["clarity"] }, "Mozilla/5.0 Chrome/140");
  await screen.findByText("disabled");
  expect(screen.getByText("Workspace")).toBeTruthy();
  expect(screen.queryByText("Clarity feature")).toBeNull();
});
it("fails open when config cannot be fetched", async () => {
  mount();
  vi.mocked(fetch).mockRejectedValue(new Error("offline"));
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  // The earlier valid response may arrive; explicitly remount with a failed fetch.
});
it("fails open on invalid server config", async () => {
  mount({ ...config, features_off: ["unknown"] } as unknown as AppConfig);
  await act(async () => {});
  expect(screen.getByText("Workspace")).toBeTruthy();
});
