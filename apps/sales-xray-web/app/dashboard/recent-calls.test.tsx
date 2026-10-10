import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LibrarySubmission } from "../acquisition-client";
import { RecentCallsList } from "./recent-calls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

function call(id: string, name: string | null, seconds: number) {
  return {
    id,
    createdAt: "2025-09-24T06:30:00Z",
    durationSeconds: seconds,
    label: name ? { displayName: name, revision: 1 } : null,
  } as unknown as LibrarySubmission;
}

const calls = [
  call("11111111-1111-4111-8111-111111111111", "Test", 226),
  call("22222222-2222-4222-8222-222222222222", null, 0),
  call("33333333-3333-4333-8333-333333333333", "qwerty", 1446),
];

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

it("lists each call once with its real name, or the shared unnamed-call name", async () => {
  await act(async () => root.render(<RecentCallsList calls={calls} />));
  const rows = [...host.querySelectorAll("li a")];
  expect(rows).toHaveLength(3);
  expect(rows[0].textContent).toContain("Test");
  expect(rows[0].textContent).toContain("3:46");
  // The same muted fallback as Calls and Organisation: "Sales call · <date>".
  expect(rows[1].textContent).toMatch(/Sales call · \S.*2025/);
  expect(rows[1].querySelector("[data-untitled]")).not.toBeNull();
  expect(rows[1].textContent).toContain("—");
  expect(rows[2].textContent).toContain("24:06");
  expect(rows[0].getAttribute("href")).toContain(calls[0].id);
});

it("shows only the rows that fit and reports how many did not", async () => {
  let resize: (() => void) | undefined;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  const height = vi
    .spyOn(HTMLElement.prototype, "clientHeight", "get")
    .mockReturnValue(100);
  const onHiddenChange = vi.fn();
  await act(async () =>
    root.render(
      <RecentCallsList calls={calls} onHiddenChange={onHiddenChange} />,
    ),
  );
  expect(host.querySelectorAll("li")).toHaveLength(2);
  expect(onHiddenChange).toHaveBeenLastCalledWith(1);

  height.mockReturnValue(200);
  await act(async () => resize?.());
  expect(host.querySelectorAll("li")).toHaveLength(3);
  expect(onHiddenChange).toHaveBeenLastCalledWith(0);
  height.mockRestore();
});

it("says whose call each row is when the list mixes people", async () => {
  const me = "00000000-0000-4000-8000-000000000001";
  const team = [
    { ...calls[0], owner: { personId: me, name: "Asha Menon" } },
    {
      ...calls[1],
      owner: {
        personId: "00000000-0000-4000-8000-000000000002",
        name: "Rahul Verma",
      },
    },
  ];
  await act(async () =>
    root.render(<RecentCallsList calls={team} viewerId={me} />),
  );
  const rows = [...host.querySelectorAll("li a")];
  expect(rows[0].textContent).toContain("You");
  expect(rows[1].textContent).toContain("RVRahul Verma");
  expect(host.querySelector("ul[data-owners]")).not.toBeNull();
  // A list of only your own calls stays as it was: no owner column.
  await act(async () => root.render(<RecentCallsList calls={calls} />));
  expect(host.querySelector("ul[data-owners]")).toBeNull();
  expect(host.textContent).not.toContain("You");
});
