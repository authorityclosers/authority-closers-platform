// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: router.replace,
    push: vi.fn(),
    prefetch: vi.fn(),
  }),
}));
const load = vi.hoisted(() => ({ requested: vi.fn() }));
vi.mock("./account-settings", () => {
  load.requested();
  return { AccountSettings: () => null };
});

import { SettingsDialogHost } from "./settings-dialog";
import { openSettings } from "./settings-open";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("loads no settings screen in the frame: opening settings goes to its page", async () => {
  window.history.replaceState(null, "", "/dashboard");
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: "t" },
          retry: () => {},
        }}
      >
        <SettingsDialogHost />
      </WorkspaceAccessProvider>,
    ),
  );
  await act(async () => openSettings("usage"));
  expect(router.replace).toHaveBeenCalledWith("/settings/plan");
  expect(load.requested).not.toHaveBeenCalled();
  expect(host.innerHTML).toBe("");
  await act(async () => root.unmount());
  host.remove();
});
