// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import { reflexRequest } from "./validation";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
let replace: ReturnType<typeof vi.spyOn>;
const challenge = "a".repeat(43);
const path = `/connect/reflex?challenge=${challenge}&return=%2Flearning`;
beforeEach(() => {
  window.history.replaceState({}, "", path);
  replace = vi.spyOn(window.location, "replace").mockImplementation(() => {});
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("starts once in StrictMode and replaces with the sealed learner URL", async () => {
  const url = "https://learner.authorityclosers.com/auth/handoff#code=sealed";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ url }))),
  );
  await act(async () =>
    root.render(
      <StrictMode>
        <Page />
      </StrictMode>,
    ),
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith(
    "/v1/auth/handoff/start",
    expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      body: JSON.stringify({
        target: "learner",
        challenge,
        return_path: "/learning",
      }),
    }),
  );
  expect(replace).toHaveBeenCalledExactlyOnceWith(url);
});
it("uses normal Sales sign-in and returns to the exact connector URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 401 })),
  );
  await act(async () => root.render(<Page />));
  expect(replace).toHaveBeenCalledExactlyOnceWith(
    `/login?next=${encodeURIComponent(path)}`,
  );
});
it("shows calm loading with a kit skeleton while pending", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  await act(async () => root.render(<Page />));
  expect(container.textContent).toContain("Opening Reflex…");
  expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
});
it("shows the kit empty state and retries", async () => {
  const url = "https://learner.authorityclosers.com/auth/handoff#code=fresh";
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ url }))),
  );
  await act(async () => root.render(<Page />));
  expect(container.textContent).toContain("Couldn't open Reflex");
  expect(container.querySelector('a[href="/dashboard"]')?.textContent).toBe(
    "Back to Sales X-Ray",
  );
  await act(async () =>
    container.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(replace).toHaveBeenCalledWith(url);
});
it.each([
  "https://x",
  "//x",
  "\\x",
  "/\\x",
  "a".repeat(600),
  "/a\nb",
  "/a\x7fb",
  "/a\x85b",
])("rejects unsafe return before fetching %s", async (bad) => {
  window.history.replaceState(
    {},
    "",
    `/connect/reflex?${new URLSearchParams({ challenge, return: bad })}`,
  );
  vi.stubGlobal("fetch", vi.fn());
  await act(async () => root.render(<Page />));
  expect(fetch).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Couldn't open Reflex");
});
it.each([
  "",
  "a".repeat(42),
  "a".repeat(44),
  "+".repeat(43),
  "a".repeat(42) + "\n",
])("rejects malformed challenge %s", (bad) =>
  expect(
    reflexRequest(`?${new URLSearchParams({ challenge: bad })}`),
  ).toBeNull(),
);
it("defaults to home and refuses duplicate query fields", () => {
  expect(reflexRequest(`?challenge=${challenge}`)?.return_path).toBe("/home");
  expect(
    reflexRequest(`?challenge=${challenge}&challenge=${challenge}`),
  ).toBeNull();
  expect(
    reflexRequest(`?challenge=${challenge}&return=/home&return=/learning`),
  ).toBeNull();
});
