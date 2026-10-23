// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { BugActions } from "./bug-actions";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  refresh.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

function select(label: string): HTMLSelectElement {
  const field = [...host.querySelectorAll("label")].find((item) =>
    item.textContent?.startsWith(label),
  );
  return field!.querySelector("select")!;
}

function choose(
  element: HTMLSelectElement | HTMLTextAreaElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLTextAreaElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
    element,
    value,
  );
  element.dispatchEvent(
    new Event(element instanceof HTMLSelectElement ? "change" : "input", {
      bubbles: true,
    }),
  );
}

const save = () =>
  act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });

it("suggests the next status and saves only what changed", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <BugActions bugId="b1" status="new" severity={null} area="leads" />,
    ),
  );
  expect(select("Status").value).toBe("triaged");
  await act(async () => choose(select("Severity"), "high"));
  await save();
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/v1/admin/bugs/b1/events");
  expect(JSON.parse(String(init.body))).toEqual({
    status: "triaged",
    severity: "high",
  });
  expect(refresh).toHaveBeenCalled();
  expect(host.textContent).toContain("Saved to the bug's history.");
});

it("asks why before closing, and shows the API's refusal in place", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ detail: "That report is not here." }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <BugActions bugId="b2" status="triaged" severity="low" area="calls" />,
    ),
  );
  await act(async () => choose(select("Status"), "closed"));
  expect(host.textContent).toContain("Why it is closed");
  await save();
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Say why it is closed",
  );
  await act(async () =>
    choose(host.querySelector("textarea")!, "Same as bug 12"),
  );
  await save();
  expect(
    JSON.parse(
      String(
        (fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body,
      ),
    ),
  ).toEqual({
    status: "closed",
    note: "Same as bug 12",
  });
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "That report is not here.",
  );
  expect(refresh).not.toHaveBeenCalled();
});
