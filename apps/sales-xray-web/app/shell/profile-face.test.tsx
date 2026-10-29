import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { WorkspaceAccessProvider } from "../workspace-access";
import { invalidateShellProfile, useShellProfile } from "./profile-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const profile = {
  name: "Morgan Lee",
  email: "morgan@example.test",
  photo_url: "/v1/me/sales-xray-profile/photo",
  phone_number_e164: null,
  phone_verified: false,
  profile_complete: false,
  revision: 0,
};

afterEach(() => {
  invalidateShellProfile();
  vi.unstubAllGlobals();
});

function Face({ id, keep }: { id: string; keep: boolean }) {
  return <p data-face={id}>{useShellProfile(true, true, keep)?.name}</p>;
}

const host = document.createElement("div");
const shown = (id: string) =>
  host.querySelector(`[data-face="${id}"]`)?.textContent || null;

const frame = (tenantId: string) => (
  <WorkspaceAccessProvider
    value={{
      status: "ready",
      authenticated: true,
      context: { personId: "p", sessionId: "s", tenantId },
      retry: () => {},
    }}
  >
    <Face id="frame" keep />
    <Face id="form" keep={false} />
  </WorkspaceAccessProvider>
);

const settle = () =>
  act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });

// Owner bugs #17 and #50 (29 Oct 2026): a workspace switch lands in place, so
// the frame keeps your own face and name while the new workspace's profile is
// read; anything else waits for that read.
it("keeps your face in the frame while another workspace's profile is read", async () => {
  let answer!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json(profile))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            answer = done;
          }),
      ),
  );
  const root = createRoot(host);
  await act(async () => root.render(frame("one")));
  await settle();
  expect(shown("frame")).toBe("Morgan Lee");
  await act(async () => root.render(frame("two")));
  expect(shown("frame")).toBe("Morgan Lee");
  expect(shown("form")).toBeNull();
  await act(async () =>
    answer(Response.json({ ...profile, name: "Morgan Lee Rivera" })),
  );
  await settle();
  expect(shown("frame")).toBe("Morgan Lee Rivera");
  expect(shown("form")).toBe("Morgan Lee Rivera");
  await act(async () => root.unmount());
});

it("forgets your face when you sign out", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => Promise.resolve(Response.json(profile))),
  );
  const root = createRoot(host);
  await act(async () => root.render(frame("one")));
  await settle();
  expect(shown("frame")).toBe("Morgan Lee");
  invalidateShellProfile();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => new Promise<Response>(() => undefined)),
  );
  await act(async () => root.render(frame("two")));
  expect(shown("frame")).toBeNull();
  await act(async () => root.unmount());
});
