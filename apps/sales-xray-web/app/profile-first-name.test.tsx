// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  readAccountProfile,
  type AccountProfileRecord,
} from "./account-profile-client";
import { useProfileFirstName } from "./profile-first-name";
import { updateShellState } from "./shell/shell-store";

vi.mock("./account-profile-client", () => ({
  readAccountProfile: vi.fn(),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function FirstName() {
  return <span>{useProfileFirstName() ?? ""}</span>;
}

function profile(name: string | null): AccountProfileRecord {
  return {
    name,
    email: "person@example.test",
    phone_number_e164: null,
    phone_verified: false,
    profile_complete: false,
    revision: 0,
  };
}

describe("useProfileFirstName", () => {
  let root: Root | undefined;
  let host: HTMLDivElement;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.append(host);
    updateShellState({ profileName: null });
    vi.clearAllMocks();
  });

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    root = undefined;
    host.remove();
    updateShellState({ profileName: null });
    vi.unstubAllEnvs();
  });

  it("keeps the server and initial client render name-free, then uses cache", async () => {
    vi.stubEnv("NODE_ENV", "development");
    updateShellState({ profileName: "  Ada Lovelace " });
    expect(renderToString(<FirstName />)).toBe("<span></span>");

    const mountedRoot = createRoot(host);
    root = mountedRoot;
    act(() => mountedRoot.render(<FirstName />));
    expect(host.textContent).toBe("");

    await act(async () => {
      await Promise.resolve();
    });
    expect(host.textContent).toBe("Ada");
    expect(readAccountProfile).not.toHaveBeenCalled();
  });

  it("reads the canonical profile when no cache exists", async () => {
    vi.stubEnv("NODE_ENV", "development");
    let resolveProfile!: (value: AccountProfileRecord) => void;
    vi.mocked(readAccountProfile).mockReturnValue(
      new Promise((resolve) => {
        resolveProfile = resolve;
      }),
    );

    const mountedRoot = createRoot(host);
    root = mountedRoot;
    act(() => mountedRoot.render(<FirstName />));
    expect(host.textContent).toBe("");
    expect(readAccountProfile).toHaveBeenCalledOnce();
    const signal = vi.mocked(readAccountProfile).mock.calls[0]?.[0];
    expect(signal).toBeInstanceOf(AbortSignal);

    await act(async () => resolveProfile(profile(" Ada Lovelace ")));
    expect(host.textContent).toBe("Ada");
  });

  it.each([null, "   "])(
    "keeps the no-name fallback when the canonical profile name is %s",
    async (name) => {
      vi.stubEnv("NODE_ENV", "development");
      vi.mocked(readAccountProfile).mockResolvedValue(profile(name));

      const mountedRoot = createRoot(host);
      root = mountedRoot;
      await act(async () => mountedRoot.render(<FirstName />));

      expect(host.textContent).toBe("");
    },
  );

  it("keeps the no-name fallback when the canonical profile read fails", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.mocked(readAccountProfile).mockRejectedValue(new Error("unavailable"));

    const mountedRoot = createRoot(host);
    root = mountedRoot;
    await act(async () => mountedRoot.render(<FirstName />));

    expect(host.textContent).toBe("");
  });

  it("aborts the profile read and ignores a late response after unmount", async () => {
    vi.stubEnv("NODE_ENV", "development");
    let resolveProfile!: (value: AccountProfileRecord) => void;
    vi.mocked(readAccountProfile).mockReturnValue(
      new Promise((resolve) => {
        resolveProfile = resolve;
      }),
    );

    const mountedRoot = createRoot(host);
    root = mountedRoot;
    act(() => mountedRoot.render(<FirstName />));
    const signal = vi.mocked(readAccountProfile).mock.calls[0]?.[0];
    expect(signal).toBeInstanceOf(AbortSignal);

    await act(async () => mountedRoot.unmount());
    root = undefined;
    expect(signal?.aborted).toBe(true);

    const readLateName = vi.fn(() => "Ada Lovelace");
    const lateProfile: AccountProfileRecord = {
      get name() {
        return readLateName();
      },
      email: "person@example.test",
      phone_number_e164: null,
      phone_verified: false,
      profile_complete: false,
      revision: 0,
    };
    await act(async () => {
      resolveProfile(lateProfile);
      await Promise.resolve();
    });
    expect(readLateName).not.toHaveBeenCalled();
  });

  it("keeps the existing test-environment profile request guard", async () => {
    const mountedRoot = createRoot(host);
    root = mountedRoot;
    await act(async () => mountedRoot.render(<FirstName />));

    expect(host.textContent).toBe("");
    expect(readAccountProfile).not.toHaveBeenCalled();
  });
});
