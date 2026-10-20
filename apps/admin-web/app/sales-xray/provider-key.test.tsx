// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import {
  keyTestWords,
  normalizeHub,
  normalizeKeys,
  type HubProvider,
} from "./provider-hub-data";
import { ProviderKey } from "./provider-key";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const [GEMINI] = normalizeHub({
  providers: [
    {
      id: "gemini",
      name: "Google Gemini",
      kind: "llm",
      console: "https://aistudio.google.com",
      pipeline: "ready",
      models: 3,
    },
  ],
}).providers as [HubProvider];

const KEYS = {
  environment: "dev",
  sealing: true,
  fresh_minutes: 10,
  keys: [
    {
      provider: "gemini",
      hint: "a1b2",
      added_at: "2026-10-19T10:00:00Z",
      free_check: true,
      tested: {
        at: "2026-10-20T11:00:00Z",
        ok: false,
        status: 402,
        models: null,
        words:
          "Out of credit, or billing is not set up. Top up in the provider's console.",
        fix: "console",
      },
    },
    { provider: "", hint: "zzzz" },
  ],
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (text: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === text,
  );

it("reads keys without ever holding one, and words every test", () => {
  const keys = normalizeKeys(KEYS);
  expect(Object.keys(keys.keys)).toEqual(["gemini"]);
  expect(keys.keys.gemini?.tested).toMatchObject({ ok: false, status: 402 });
  expect(JSON.stringify(keys)).not.toContain("key-");
  const base = { at: "", status: 200, models: 12, words: "", fix: null };
  expect(keyTestWords({ ...base, ok: true })).toBe(
    "The key works: 12 models listed.",
  );
  expect(keyTestWords({ ...base, ok: true, models: null })).toBe(
    "The key works.",
  );
  expect(keyTestWords({ ...base, ok: null })).toContain("no free check");
  expect(keyTestWords({ ...base, ok: false, status: 401 })).toContain(
    "HTTP 401",
  );
});

it("shows the held key by its last four characters, the failed test and the fix", async () => {
  await act(async () =>
    root.render(<ProviderKey provider={GEMINI} keys={normalizeKeys(KEYS)} />),
  );
  const text = host.textContent ?? "";
  expect(text).toContain("Key in dev");
  expect(text).toContain("Key ending a1b2");
  expect(text).toContain("Not working");
  expect(text).toContain("Out of credit");
  expect(
    host.querySelector('a[href="https://aistudio.google.com"]')?.textContent,
  ).toBe("Top up credit");
  expect(button("Test connection")).toBeDefined();
  expect(button("Replace key")).toBeDefined();
  expect(button("Remove")).toBeDefined();
});

it("seals a pasted key and empties the field, sending it only to the API", async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    status: 201,
    json: async () => ({ provider: "gemini", hint: "wxyz" }),
  }));
  vi.stubGlobal("fetch", fetcher);
  const keys = normalizeKeys({ ...KEYS, keys: [] });
  await act(async () =>
    root.render(<ProviderKey provider={GEMINI} keys={keys} />),
  );
  expect(host.textContent).toContain("No key here yet");
  await act(async () => button("Add key")?.click());
  const input = host.querySelector<HTMLInputElement>('input[type="password"]');
  expect(input?.autocomplete).toBe("off");
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(input, "fictional-key-wxyz");
    input?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Seal key")?.click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/v1/admin/providers/gemini/key");
  expect(init.method).toBe("POST");
  expect(JSON.parse(String(init.body))).toEqual({ key: "fictional-key-wxyz" });
  expect(refresh).toHaveBeenCalled();
  expect(host.innerHTML).not.toContain("fictional-key-wxyz");
});

it("says when this environment cannot seal keys yet, and offers nothing to paste", async () => {
  const keys = normalizeKeys({ ...KEYS, sealing: false, keys: [] });
  await act(async () =>
    root.render(<ProviderKey provider={GEMINI} keys={keys} />),
  );
  expect(host.textContent).toContain("Keys can't be sealed in dev yet");
  expect(button("Add key")).toBeUndefined();
  expect(host.querySelector("input")).toBeNull();
});
