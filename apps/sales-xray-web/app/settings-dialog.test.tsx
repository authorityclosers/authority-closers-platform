// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    replace,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { replace?: boolean }) => (
    <a
      {...props}
      href={href}
      onClick={(event) => {
        const navigate =
          !event.defaultPrevented &&
          event.button === 0 &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.shiftKey &&
          !event.altKey &&
          (!event.currentTarget.target ||
            event.currentTarget.target === "_self") &&
          !event.currentTarget.hasAttribute("download");
        event.preventDefault();
        if (navigate)
          window.history[replace ? "replaceState" : "pushState"](
            null,
            "",
            href,
          );
      }}
    />
  ),
}));

import { SettingsDialogHost } from "./settings-dialog";
import { closeSettings, openSettings } from "./settings-open";
import { GuideProgressStore } from "./guide-progress";
import { FIRST_CALL_GUIDE } from "./guide-registry";
import { UploadSessionProvider } from "./hooks/upload-session";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function flush() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
    if (host.querySelector("dialog"))
      await vi.waitFor(
        () => {
          const dialog = host.querySelector("dialog");
          expect(
            dialog === null ||
              dialog.querySelector('[role="tab"][aria-selected="true"]') !==
                null,
          ).toBe(true);
        },
        { timeout: 3000 },
      );
  });
}

async function render(authenticated: boolean, personId: string | null = "p") {
  await act(async () =>
    root.render(
      <UploadSessionProvider>
        <WorkspaceAccessProvider
          value={{
            status: authenticated ? "ready" : "unauthenticated",
            authenticated,
            context:
              authenticated && personId
                ? { personId, sessionId: "s", tenantId: "t" }
                : null,
            retry: () => {},
          }}
        >
          <SettingsDialogHost />
        </WorkspaceAccessProvider>
      </UploadSessionProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/dashboard");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo) => {
      const path = String(input).split("?")[0];
      if (path === "/v1/me/sales-xray-profile")
        return json({
          name: "Asha Rao",
          email: "asha@example.invalid",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: false,
          revision: 1,
        });
      return json({}, 404);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("floats settings over the current page and closes back to it", async () => {
  await render(true);
  expect(host.querySelector("dialog")).toBeNull();
  await act(async () => openSettings("profile"));
  await flush();
  const dialog = host.querySelector("dialog")!;
  expect(dialog).not.toBeNull();
  expect(window.location.pathname).toBe("/dashboard");
  expect(window.location.hash).toBe("#settings/profile");
  expect(
    dialog.querySelector('[role="tab"][aria-selected="true"]')?.textContent,
  ).toContain("Profile");
  expect(dialog.textContent).toContain("Asha Rao");
  await act(async () => closeSettings("replace"));
  await flush();
  expect(host.querySelector("dialog")).toBeNull();
  expect(window.location.hash).toBe("");
});

it("never opens account settings for a signed-out visitor", async () => {
  await render(false);
  await act(async () => openSettings());
  await flush();
  expect(host.querySelector("dialog")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

it("restarts the dismissed guide from Help and closes Settings so it can be seen", async () => {
  new GuideProgressStore("p", FIRST_CALL_GUIDE).update({
    stepId: "moments",
    status: "skipped",
  });
  await render(true);
  await act(async () => openSettings("help"));
  await flush();
  const toggle = host.querySelector<HTMLButtonElement>(
    '[role="switch"][aria-label="First call guide"]',
  )!;
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  await act(async () => toggle.click());
  await flush();
  expect(host.querySelector("dialog")).toBeNull();
  expect(window.location.hash).toBe("");
  expect(new GuideProgressStore("p", FIRST_CALL_GUIDE).getSnapshot()).toEqual({
    stepId: "welcome",
    status: "active",
  });
});

it("keeps Help open when switching the guide off, remembers it, and isolates accounts", async () => {
  await render(true);
  await act(async () => openSettings("help"));
  await flush();
  const getToggle = () =>
    host.querySelector<HTMLButtonElement>(
      '[role="switch"][aria-label="First call guide"]',
    )!;
  expect(getToggle().getAttribute("aria-checked")).toBe("true");
  await act(async () => getToggle().click());
  await flush();
  expect(getToggle().getAttribute("aria-checked")).toBe("false");
  expect(host.querySelector("dialog")).not.toBeNull();
  await act(async () => closeSettings("replace"));
  await act(async () => openSettings("help"));
  await flush();
  expect(getToggle().getAttribute("aria-checked")).toBe("false");
  await render(true, "q");
  expect(getToggle().getAttribute("aria-checked")).toBe("true");
  await render(true, "p");
  expect(getToggle().getAttribute("aria-checked")).toBe("false");
});

it("hides the guide switch until the signed-in account identity is known", async () => {
  await render(true, null);
  await act(async () => openSettings("help"));
  await flush();
  expect(host.querySelector("dialog")).not.toBeNull();
  expect(host.querySelector('[aria-label="First call guide"]')).toBeNull();
  expect(
    host.querySelector('#account-pane-help a[href^="mailto:"]'),
  ).not.toBeNull();
});

it("replaces the settings entry with an internal destination", async () => {
  await render(true);
  const initialLength = window.history.length;
  await act(async () => openSettings("profile"));
  await flush();
  expect(window.history.length).toBe(initialLength + 1);
  const link = host.querySelector<HTMLAnchorElement>(
    'a[href="/analysis/calls"]',
  )!;
  await act(async () => link.click());
  await flush();
  expect(window.location.pathname).toBe("/analysis/calls");
  expect(window.location.hash).toBe("");
  expect(window.history.length).toBe(initialLength + 1);
  expect(host.querySelector("dialog")).toBeNull();
});

it.each(["ctrl", "meta", "shift", "blank", "download"])(
  "preserves the open settings entry for a %s link click",
  async (kind) => {
    await render(true);
    await act(async () => openSettings("profile"));
    await flush();
    const link = host.querySelector<HTMLAnchorElement>(
      'a[href="/analysis/calls"]',
    )!;
    if (kind === "blank") link.target = "_blank";
    if (kind === "download") link.download = "report";
    await act(async () =>
      link.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          ctrlKey: kind === "ctrl",
          metaKey: kind === "meta",
          shiftKey: kind === "shift",
        }),
      ),
    );
    expect(window.location.pathname).toBe("/dashboard");
    expect(window.location.hash).toBe("#settings/profile");
    expect(host.querySelector("dialog")).not.toBeNull();
  },
);
