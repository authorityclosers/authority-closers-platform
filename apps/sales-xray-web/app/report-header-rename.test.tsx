import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AcquisitionError } from "./acquisition-client";
import type { CallLabel } from "./call-label";
import { ReportHeader, type ReportHeaderProps } from "./report-header";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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
});

function Header(props: Partial<ReportHeaderProps>) {
  return (
    <ReportHeader
      durationMs={3_598_000}
      sourceLabel="Fictional transcript"
      claimed
      busy={false}
      canDownload
      canRequestDeletion
      deletionDisabled={false}
      onAnalyseAnother={() => {}}
      onDownload={() => {}}
      onRequestDeletion={() => {}}
      {...props}
    />
  );
}

const title = () => host.querySelector("h1")?.textContent;
const rename = () =>
  host.querySelector<HTMLButtonElement>('button[aria-label^="Rename call"]');
const input = () =>
  host.querySelector<HTMLInputElement>("[data-call-label-editor] input")!;
const setInput = (value: string) => {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input(), value);
  input().dispatchEvent(new Event("input", { bubbles: true }));
};
const submit = () =>
  act(async () =>
    host
      .querySelector("[data-call-label-editor]")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );

it("titles the report with the confirmed name and renames through the server", async () => {
  let label: CallLabel = { displayName: "Old name", revision: 4 };
  const save = vi.fn(async (name: string | null, revision: number) => ({
    displayName: name,
    revision: revision + 1,
  }));
  const render = () =>
    root.render(
      <Header
        label={label}
        rename={{
          save,
          refresh: async () => label,
          confirmed: (next) => {
            label = next;
            void act(async () => render());
          },
        }}
      />,
    );
  await act(async () => render());
  expect(title()).toBe("Old name");
  await act(async () => rename()!.click());
  await act(async () => setInput("Renewal review"));
  await submit();
  expect(save).toHaveBeenCalledWith("Renewal review", 4, expect.anything());
  expect(title()).toBe("Renewal review");
  expect(host.querySelector("[data-call-label-editor]")).toBeNull();
});

it("keeps the draft and the old title when the server refuses", async () => {
  const save = vi.fn(async () => {
    throw new AcquisitionError(403);
  });
  await act(async () =>
    root.render(
      <Header
        label={{ displayName: null, revision: 0 }}
        rename={{ save, refresh: async () => null, confirmed: vi.fn() }}
      />,
    ),
  );
  expect(title()).toBe("Sales call report");
  await act(async () => rename()!.click());
  await act(async () => setInput("Not allowed"));
  await submit();
  expect(input().value).toBe("Not allowed");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Only the signed-in account that saved this call can rename it",
  );
  expect(host.textContent).not.toContain("Not allowed call");
});

it("offers rename only for a claimed call on a server that supplies labels", async () => {
  const rename_ = { save: vi.fn(), refresh: vi.fn(), confirmed: vi.fn() };
  await act(async () =>
    root.render(
      <Header
        claimed={false}
        label={{ displayName: null, revision: 0 }}
        rename={rename_}
      />,
    ),
  );
  expect(rename()).toBeNull();
  await act(async () => root.render(<Header label={null} rename={rename_} />));
  expect(rename()).toBeNull();
  expect(title()).toBe("Sales call report");
});
