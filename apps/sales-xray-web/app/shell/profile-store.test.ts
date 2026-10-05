import { afterEach, expect, it, vi } from "vitest";
import { getShellState } from "./shell-store";
import { invalidateShellProfile, readShellProfile } from "./profile-store";
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
it("shares one unabortable request and caches the canonical name and photo across consumers", async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn<(path: string, init: RequestInit) => Promise<Response>>(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const first = readShellProfile("account/session/workspace");
  expect(readShellProfile("account/session/workspace")).toBe(first);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0]?.[1].signal).toBeUndefined();
  resolve(Response.json(profile));
  await expect(first).resolves.toEqual(profile);
  expect(getShellState().profileName).toBe("Morgan Lee");
  await expect(readShellProfile("account/session/workspace")).resolves.toEqual(
    profile,
  );
  expect(fetcher).toHaveBeenCalledOnce();
});
it("does not reuse a profile after invalidation or a session/workspace change", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation(() => Promise.resolve(Response.json(profile)));
  vi.stubGlobal("fetch", fetcher);
  await readShellProfile("first/session/workspace");
  invalidateShellProfile();
  expect(getShellState().profileName).toBeNull();
  await readShellProfile("first/session/workspace");
  await readShellProfile("second/session/workspace");
  expect(fetcher).toHaveBeenCalledTimes(3);
});
it("rejects an obsolete in-flight response without replacing the new account", async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    )
    .mockResolvedValueOnce(Response.json({ ...profile, name: "Alex Rivera" }));
  vi.stubGlobal("fetch", fetcher);
  const old = readShellProfile("old");
  const rejected = expect(old).rejects.toThrow("profile_read_superseded");
  await readShellProfile("new");
  resolve(Response.json(profile));
  await rejected;
  expect(getShellState().profileName).toBe("Alex Rivera");
});
it("does not retry failures until the next consumer asks", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValueOnce(Response.json(profile));
  vi.stubGlobal("fetch", fetcher);
  await expect(readShellProfile("same")).rejects.toThrow("unavailable");
  expect(fetcher).toHaveBeenCalledOnce();
  await expect(readShellProfile("same")).resolves.toEqual(profile);
  expect(fetcher).toHaveBeenCalledTimes(2);
});
