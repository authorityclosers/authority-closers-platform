// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { SettingsDialogHost } from "./settings-dialog";
import { closeSettings, openSettings } from "./settings-open";
import { WorkspaceAccessProvider } from "./workspace-access";

const load = vi.hoisted(() => {
  let resolve!: () => void;
  const pending = new Promise<void>((done) => {
    resolve = done;
  });
  return { pending, resolve, requested: vi.fn() };
});

vi.mock("./account-settings", async () => {
  load.requested();
  await load.pending;
  return {
    AccountSettings: ({ onClose }: { onClose: () => void }) => (
      <button onClick={onClose}>Close loaded settings</button>
    ),
  };
});

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("loads settings only on open, announces the wait, and closes before and after it resolves", async () => {
  window.history.replaceState(null, "", "/dashboard");
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
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
    expect(load.requested).not.toHaveBeenCalled();
    await act(async () => openSettings("profile"));
    await vi.waitFor(() =>
      expect(host.querySelector('[role="status"]')).not.toBeNull(),
    );
    const status = host.querySelector('[role="status"]');
    expect(status?.textContent).toBe("Loading…");
    expect(status?.getAttribute("aria-live")).toBe("polite");
    expect(status?.getAttribute("aria-busy")).toBe("true");
    await act(async () => closeSettings("replace"));
    expect(host.querySelector("dialog")).toBeNull();
    await act(async () => load.resolve());
    expect(host.querySelector("dialog")).toBeNull();
    await act(async () => openSettings("profile"));
    await vi.waitFor(() =>
      expect(host.textContent).toContain("Close loaded settings"),
    );
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(host.querySelector("dialog")).toBeNull();
    expect(window.location.hash).toBe("");
  } finally {
    load.resolve();
    await act(async () => root.unmount());
    host.remove();
    window.history.replaceState(null, "", "/dashboard");
  }
});
