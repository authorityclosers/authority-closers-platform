import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeProvider } from "./lightbox/theme-provider";
import { PROFILE_UPDATED_EVENT, ProfileMenu } from "./profile-menu";
import { WorkspaceAccessProvider } from "./workspace-access";

vi.mock("./live-data-banner", () => ({ LocalSettingsButton: () => null }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, host: HTMLDivElement;
const profile = (name: string | null) => ({
  name,
  email: "morgan@example.invalid",
  phone_number_e164: null,
  phone_verified: false,
  profile_complete: Boolean(name),
  revision: 1,
});
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.setItem("ac.xray.submission.v1", "opaque-synthetic-selector");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-preference");
  document.documentElement.style.colorScheme = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function signOut() {
  await act(async () =>
    root.render(<ProfileMenu authenticated accountHref="/calls" />),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Sign out")!
      .click(),
  );
}
it.each(["header", "rail"] as const)(
  "shows the canonical profile name in the signed-in menu (%s)",
  async (variant) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json(profile("Morgan Lee"))),
    );
    await act(async () =>
      root.render(
        <ProfileMenu authenticated accountHref="/calls" variant={variant} />,
      ),
    );
    const trigger = host.querySelector<HTMLButtonElement>(
      "button[aria-expanded]",
    )!;
    expect(trigger.getAttribute("aria-label")).toBe("Open Morgan Lee menu");
    expect(trigger.textContent).toContain(
      variant === "header" ? "Morgan" : "Morgan Lee",
    );
    if (variant === "header")
      expect(
        trigger.querySelector("span:not([aria-hidden])")?.textContent,
      ).toBe("Morgan");
    expect(trigger.querySelector('[aria-hidden="true"]')?.textContent).toBe(
      "ML",
    );
    await act(async () => trigger.click());
    expect(
      host.querySelector('[aria-label="Profile actions"] [aria-hidden="true"]')
        ?.textContent,
    ).toBe("ML");
    expect(host.querySelector('[role="region"]')?.textContent).toContain(
      "Morgan Lee",
    );
    expect(fetch).toHaveBeenCalledWith(
      "/v1/me/sales-xray-profile",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  },
);
it("keeps a neutral label when the canonical profile has no name", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json(profile(null))),
  );
  await act(async () =>
    root.render(<ProfileMenu authenticated accountHref="/calls" />),
  );
  expect(
    host
      .querySelector<HTMLButtonElement>("button[aria-expanded]")
      ?.getAttribute("aria-label"),
  ).toBe("Open AC account menu");
  expect(
    host.querySelector('button[aria-expanded] > span[aria-hidden="true"]')
      ?.textContent,
  ).toBe("AC");
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  expect(
    host.querySelector('[aria-label="Profile actions"]')?.textContent,
  ).toContain("Authority Closers account");
});
it("refreshes the name after a confirmed profile update", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json(profile("Morgan Lee")))
      .mockResolvedValueOnce(Response.json(profile("Alex Rivera"))),
  );
  await act(async () =>
    root.render(<ProfileMenu authenticated accountHref="/calls" />),
  );
  expect(
    host
      .querySelector<HTMLButtonElement>("button[aria-expanded]")
      ?.getAttribute("aria-label"),
  ).toBe("Open Morgan Lee menu");
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  expect(
    host.querySelector('[aria-label="Profile actions"]')?.textContent,
  ).toContain("Morgan Lee");
  await act(async () => window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT)));
  expect(
    host
      .querySelector<HTMLButtonElement>("button[aria-expanded]")
      ?.getAttribute("aria-label"),
  ).toBe("Open Alex Rivera menu");
  expect(
    host.querySelector('[aria-label="Profile actions"]')?.textContent,
  ).toContain("Alex Rivera");
  expect(
    host.querySelector('[aria-label="Profile actions"]')?.textContent,
  ).not.toContain("Morgan Lee");
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("does not fetch an account profile for a guest", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(<ProfileMenu authenticated={false} accountHref="/login" />),
  );
  expect(fetchMock).not.toHaveBeenCalled();
  expect(
    host
      .querySelector<HTMLButtonElement>("button[aria-expanded]")
      ?.getAttribute("aria-label"),
  ).toBe("Open profile menu");
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  expect(
    host.querySelector('[aria-label="Profile actions"]')?.textContent,
  ).toContain("Guest workspace");
  expect(
    host.querySelector('[aria-label="Profile actions"] a[href="/login"]')
      ?.textContent,
  ).toBe("Sign in");
  expect(fetchMock).not.toHaveBeenCalled();
});
it("starts inline account sign-in so a staged file can stay mounted", async () => {
  const requestAccountSignIn = vi.fn();
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "unauthenticated",
          authenticated: false,
          context: null,
          retry: () => {},
          requestAccountSignIn,
        }}
      >
        <ProfileMenu authenticated={false} accountHref="/login" />
      </WorkspaceAccessProvider>,
    ),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Sign in")!
      .click(),
  );
  expect(requestAccountSignIn).toHaveBeenCalledOnce();
  expect(host.querySelector('[aria-label="Profile actions"]')).toBeNull();
});
it("adds the theme choice after the account actions only under a released theme", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
  await act(async () =>
    root.render(
      <ThemeProvider controlEnabled>
        <ProfileMenu
          authenticated={false}
          accountHref="/login"
          placement="above"
        />
      </ThemeProvider>,
    ),
  );
  expect(host.querySelector('[data-placement="above"]')).not.toBeNull();
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  const region = host.querySelector('[role="region"]')!;
  expect(region.querySelector('[aria-hidden="true"]')?.textContent).toBe("AC");
  const theme = region.querySelector("fieldset")!;
  expect(
    theme,
    "Released profile menu must offer the Theme control",
  ).not.toBeNull();
  expect(theme.querySelector("legend")?.textContent).toBe("Theme");
  expect(
    theme.compareDocumentPosition(region.querySelector("a, button")!) &
      Node.DOCUMENT_POSITION_PRECEDING,
  ).toBeTruthy();
  await act(async () =>
    theme.querySelector<HTMLInputElement>('input[value="dark"]')!.click(),
  );
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
});
it("discards the private document only after confirmed sign out", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
  );
  await signOut();
  expect(assign).toHaveBeenCalledWith("/");
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
});
it("keeps the current session when sign out cannot be confirmed", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  await signOut();
  expect(assign).not.toHaveBeenCalled();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "couldn’t confirm sign out",
  );
  expect(localStorage.getItem("ac.xray.submission.v1")).not.toBeNull();
});
