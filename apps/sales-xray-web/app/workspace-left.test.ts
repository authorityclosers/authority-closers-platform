import { afterEach, expect, it, vi } from "vitest";
import {
  leftWorkspace,
  leftWorkspaceTitle,
  onWorkspaceLeft,
} from "./workspace-left";

afterEach(() => {
  vi.unstubAllGlobals();
});

const named = (headers: Record<string, string>) =>
  new Response(null, { status: 403, headers });

it("reads the workspace left and its name from the answer", () => {
  expect(leftWorkspace(named({}))).toBeNull();
  expect(
    leftWorkspace(
      named({
        "x-ac-workspace-left": "gone-id",
        "x-ac-workspace-left-name": "Caf%C3%A9%20Closers",
      }),
    ),
  ).toEqual({ tenantId: "gone-id", name: "Café Closers" });
  // A name that can't be read still names the workspace.
  expect(
    leftWorkspace(
      named({
        "x-ac-workspace-left": "gone-id",
        "x-ac-workspace-left-name": "%E0%A4%A",
      }),
    ),
  ).toEqual({ tenantId: "gone-id", name: null });
});

it("says plainly which workspace the person is no longer in", () => {
  expect(leftWorkspaceTitle({ tenantId: "gone-id", name: "Old Sandbox" })).toBe(
    "You're no longer in Old Sandbox",
  );
  expect(leftWorkspaceTitle({ tenantId: "gone-id", name: null })).toBe(
    "You're no longer in that workspace",
  );
});

it("hears any answer that names a workspace left and passes every answer through", async () => {
  const leaving = named({
    "x-ac-workspace-left": "gone-id",
    "x-ac-workspace-left-name": "Old%20Sandbox",
  });
  const plain = { ok: true } as unknown as Response;
  const answers = vi.fn(async (path: string) =>
    path === "/v1/left" ? leaving : plain,
  );
  vi.stubGlobal("fetch", answers);
  const heard = vi.fn();
  const stop = onWorkspaceLeft(heard);

  expect(await fetch("/v1/plain")).toBe(plain);
  expect(heard).not.toHaveBeenCalled();
  expect(await fetch("/v1/left", { method: "POST" })).toBe(leaving);
  expect(heard).toHaveBeenCalledWith({
    tenantId: "gone-id",
    name: "Old Sandbox",
  });
  // The page's own arguments reach the network unchanged.
  expect(answers.mock.calls).toEqual([
    ["/v1/plain"],
    ["/v1/left", { method: "POST" }],
  ]);

  stop();
  await fetch("/v1/left");
  expect(heard).toHaveBeenCalledTimes(1);
});
