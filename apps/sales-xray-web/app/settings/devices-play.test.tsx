// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Settings → Devices: the Google Play app updates only through Play (Play's
// Device and Network Abuse policy), so it links to no APK.
vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/devices",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../account-settings", () => ({ AccountSettings: () => null }));
vi.mock("../organisation/organisation-view", () => ({
  OrganisationView: () => null,
}));
vi.mock("../leads/alerts-card", () => ({ AlertsCard: () => null }));
vi.mock("./developers", () => ({ DevelopersSection: () => null }));
vi.mock("./connected-apps", () => ({ ConnectedApps: () => null }));
const store = vi.hoisted(() => ({ apkLinks: true }));
vi.mock("../purchase-policy", async (original) => {
  const actual = await original<typeof import("../purchase-policy")>();
  return { ...actual, useApkLinksAllowed: () => store.apkLinks };
});

import { ANDROID_APK_URL } from "../apps/release";
import { SettingsSectionView } from "./sections";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const apkLinks = () =>
  Array.from(host.querySelectorAll("a")).filter(
    (link) =>
      link.getAttribute("href") === ANDROID_APK_URL ||
      link.getAttribute("href") === "/apps",
  );

it("offers the Android download on the web and in the download-link app", async () => {
  store.apkLinks = true;
  await act(async () => root.render(<SettingsSectionView id="devices" />));
  expect(apkLinks().map((link) => link.textContent)).toEqual([
    "Get the app",
    "Download for Android",
  ]);
  expect(host.textContent).not.toContain("Google Play");
});

it("links to no APK inside the Google Play app", async () => {
  store.apkLinks = false;
  await act(async () => root.render(<SettingsSectionView id="devices" />));
  expect(apkLinks()).toEqual([]);
  expect(host.textContent).toContain(
    "You're using Sales X-Ray from Google Play. Updates come from Google Play.",
  );
  // Phone setup stays: it is how the Play app finds recordings.
  expect(host.textContent).toContain("Set up this phone");
});
