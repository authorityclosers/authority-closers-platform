// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: router.replace,
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    replace,
    onClick,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { replace?: boolean }) => (
    <a
      {...props}
      href={href}
      onClick={(event) => {
        onClick?.(event);
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
import { AccountSettings } from "./account-settings";
import { ProfileMenu } from "./profile-menu";
import { invalidateShellProfile } from "./shell/profile-store";
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
  });
}

async function render(
  authenticated: boolean,
  personId: string | null = "p",
  withProfileMenu = false,
  withHelp = false,
) {
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
          {withProfileMenu ? (
            <ProfileMenu authenticated={authenticated} accountHref="/account" />
          ) : null}
          <SettingsDialogHost />
          {withHelp ? <AccountSettings only={["help"]} /> : null}
        </WorkspaceAccessProvider>
      </UploadSessionProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  router.replace.mockReset();
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

it("opens each section of Settings in place of the entry that opened it", async () => {
  await render(true);
  await act(async () => openSettings("profile"));
  await flush();
  expect(router.replace).toHaveBeenLastCalledWith("/settings/profile");
  await act(async () => openSettings("billing"));
  await flush();
  expect(router.replace).toHaveBeenLastCalledWith("/settings/plan");
  await act(async () => openSettings());
  await flush();
  expect(router.replace).toHaveBeenLastCalledWith("/settings");
  expect(host.querySelector("dialog")).toBeNull();
  await act(async () => closeSettings("replace"));
});

it("follows an old #settings link to its section", async () => {
  window.history.replaceState(null, "", "/dashboard#settings/security");
  await render(true);
  expect(router.replace).toHaveBeenLastCalledWith("/settings/security");
});

it("keeps a sign-in provider's way back when it follows an old link", async () => {
  window.history.replaceState(
    null,
    "",
    "/?connect_error=in_use&other=1#settings/security",
  );
  await render(true);
  expect(router.replace).toHaveBeenLastCalledWith(
    "/settings/security?connect_error=in_use",
  );
});

it("never sends a signed-out visitor to Settings", async () => {
  await render(false);
  await act(async () => openSettings());
  await flush();
  expect(router.replace).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("restarts the dismissed guide from Help & support", async () => {
  new GuideProgressStore("p", FIRST_CALL_GUIDE).update({
    stepId: "moments",
    status: "skipped",
  });
  await render(true, "p", false, true);
  const toggle = host.querySelector<HTMLButtonElement>(
    '[role="switch"][aria-label="First call guide"]',
  )!;
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  // One pane inside a Settings section: the section's title names it, so
  // the pane draws no second title.
  expect(
    host.querySelector('section[aria-label="Help & support"] h2'),
  ).toBeNull();
  await act(async () => toggle.click());
  await flush();
  expect(new GuideProgressStore("p", FIRST_CALL_GUIDE).getSnapshot()).toEqual({
    stepId: "welcome",
    status: "active",
  });
});

it("switches the guide off, remembers it, and isolates accounts", async () => {
  await render(true, "p", false, true);
  const getToggle = () =>
    host.querySelector<HTMLButtonElement>(
      '[role="switch"][aria-label="First call guide"]',
    )!;
  expect(getToggle().getAttribute("aria-checked")).toBe("true");
  await act(async () => getToggle().click());
  await flush();
  expect(getToggle().getAttribute("aria-checked")).toBe("false");
  await render(true, "q", false, true);
  expect(getToggle().getAttribute("aria-checked")).toBe("true");
  await render(true, "p", false, true);
  expect(getToggle().getAttribute("aria-checked")).toBe("false");
});

it("hides the guide switch until the signed-in account identity is known", async () => {
  await render(true, null, false, true);
  expect(host.querySelector('[aria-label="First call guide"]')).toBeNull();
  expect(
    host.querySelector('#account-pane-help a[href^="mailto:"]'),
  ).not.toBeNull();
});

it("opens Profile from the pop-up in Settings", async () => {
  invalidateShellProfile();
  window.history.replaceState(
    null,
    "",
    "/analysis/calls/fictional-call?view=report",
  );
  await render(true, "p", true);
  const trigger = host.querySelector<HTMLButtonElement>(
    "button[aria-expanded]",
  )!;
  await act(async () => trigger.click());
  const profileLink = host.querySelector<HTMLAnchorElement>(
    '[aria-label="Profile actions"] a[href="/account#profile"]',
  )!;
  await act(async () => profileLink.click());
  await flush();
  expect(host.querySelector('[aria-label="Profile actions"]')).toBeNull();
  expect(router.replace).toHaveBeenLastCalledWith("/settings/profile");
  invalidateShellProfile();
});
