import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApiUploadsSwitch, readUploadTerms, TERMS_PATH } from "./api-uploads";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOTICE = {
  version: "api-upload-terms-2026-11-15",
  title: "Analyse calls our apps upload",
  text: "Calls an app sends with one of {organisation}'s API keys are analysed as soon as they arrive.",
  policy_sha256: "a".repeat(64),
};
const terms = (state: string, open = true) => ({
  state,
  open,
  message: open
    ? null
    : "API uploads aren't switched on for this workspace yet.",
  notice: open ? NOTICE : null,
  upload_policy_sha256: "b".repeat(64),
  accepted_at: null,
});

let host: HTMLDivElement;
let root: Root;
let answers: unknown[] = [];
const calls: { url: string; init?: RequestInit }[] = [];

const answer = (body: unknown, status = 200) =>
  Promise.resolve({
    ok: status < 400,
    status,
    json: async () => body,
  } as Response);

beforeEach(() => {
  calls.length = 0;
  answers = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const next = answers.shift();
      return typeof next === "number" ? answer({}, next) : answer(next);
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const flush = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
const sent = (index: number) =>
  JSON.parse(String(calls[index]?.init?.body)) as Record<string, unknown>;

it("shows nothing where API uploads can't be switched on", async () => {
  answers = [terms("closed", false)];
  await act(async () => root.render(<ApiUploadsSwitch />));
  await flush();
  expect(calls[0]?.url).toBe(TERMS_PATH);
  expect(host.textContent).toBe("");
});

it("an owner turns it on with the words shown, and off again", async () => {
  answers = [terms("ask"), terms("on"), terms("off")];
  await act(async () => root.render(<ApiUploadsSwitch />));
  await flush();
  expect(host.textContent).toContain("Analyse calls our apps upload");
  expect(host.textContent).toContain(
    "Calls an app sends with one of your organisation's API keys",
  );
  expect(host.textContent).not.toContain("{organisation}");
  expect(host.textContent).toContain("Off.");

  await act(async () => button("Turn on")!.click());
  await flush();
  expect(calls[1]?.init?.method).toBe("POST");
  expect(sent(1)).toEqual({
    decision: "granted",
    policy_sha256: "a".repeat(64),
    upload_policy_sha256: "b".repeat(64),
  });
  expect(host.textContent).toContain("On.");

  await act(async () => button("Turn off")!.click());
  await flush();
  expect(sent(2)).toEqual({ decision: "withdrawn" });
  expect(host.textContent).toContain("Off.");
});

it("a refused save says so and keeps the switch as it was", async () => {
  answers = [terms("ask"), 403];
  await act(async () => root.render(<ApiUploadsSwitch />));
  await flush();
  await act(async () => button("Turn on")!.click());
  await flush();
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "That didn’t save. Try again.",
  );
  expect(button("Turn on")).toBeDefined();
});

it("reads only the server's own shape", () => {
  expect(readUploadTerms({ state: "maybe" })).toBeNull();
  expect(readUploadTerms(null)).toBeNull();
  expect(readUploadTerms(terms("on"))?.notice?.policySha256).toBe(
    "a".repeat(64),
  );
});
