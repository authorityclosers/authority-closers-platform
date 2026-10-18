import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { parseUnknown } from "./native-phone";
import { UnknownCallsCard, unknownLine } from "./unknown-calls-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Listener = (event: { data: unknown }) => void;
type Sent = { method: string; args: Record<string, unknown> };

function fakePhone(answer: (message: Sent) => unknown) {
  const listeners: Listener[] = [];
  const sent: Sent[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as Sent & { id: string };
      sent.push({ method: message.method, args: message.args });
      const result = answer(message);
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
  return sent;
}

const now = Date.now();
const ITEMS = [
  {
    number: "+919123456789",
    lastMs: now - 60_000,
    direction: "outgoing",
    seconds: 192,
    count: 2,
  },
  {
    number: "9988776655",
    lastMs: now - 120_000,
    direction: "missed",
    seconds: 0,
    count: 1,
  },
];

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (label: string) =>
  [...host.querySelectorAll("button")].filter(
    (item) => item.textContent === label,
  );

it("shows nothing in a browser", async () => {
  await act(async () => root.render(<UnknownCallsCard onSave={() => {}} />));
  expect(host.innerHTML).toBe("");
});

it("offers to save a work call's number, and stops asking for Not a lead", async () => {
  let items = [...ITEMS];
  const sent = fakePhone((message) => {
    if (message.method === "ignoreNumber")
      items = items.filter((item) => item.number !== message.args.number);
    return { items };
  });
  const onSave = vi.fn();
  await act(async () => root.render(<UnknownCallsCard onSave={onSave} />));
  expect(host.textContent).toContain("Save as a lead?");
  expect(host.textContent).toContain("stay on your phone");
  expect(host.textContent).toContain("You called · 3:12");
  expect(host.textContent).toContain("2 calls");
  await act(async () => button("Save")[0].click());
  expect(onSave).toHaveBeenCalledWith("+919123456789");
  await act(async () => button("Not a lead")[1].click());
  expect(sent.at(-1)).toEqual({
    method: "ignoreNumber",
    args: { number: "9988776655" },
  });
  expect(host.querySelectorAll("li")).toHaveLength(1);
});

it("reads only well-formed calls", () => {
  expect(parseUnknown(null)).toEqual([]);
  expect(
    parseUnknown({ items: [{ number: "1", direction: "voicemail" }, 4] }),
  ).toEqual([]);
  const [missed] = parseUnknown({ items: [ITEMS[1]] });
  expect(unknownLine(missed)).toMatch(/^Missed · today /);
});
