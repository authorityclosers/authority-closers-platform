import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AcquisitionError } from "./acquisition-client";
import { CallLabelContractError, type CallLabel } from "./call-label";
import { CallLabelEditor } from "./call-label-editor";

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

type Save = (
  name: string | null,
  revision: number,
  signal: AbortSignal,
) => Promise<CallLabel>;
type Refresh = (signal: AbortSignal) => Promise<CallLabel | null>;

async function mount(
  save: Save,
  refresh: Refresh,
  label: CallLabel = { displayName: "Old", revision: 2 },
) {
  const confirmed = vi.fn();
  const close = vi.fn();
  await act(async () =>
    root.render(
      <CallLabelEditor
        label={label}
        onSave={save}
        onRefresh={refresh}
        onConfirmed={confirmed}
        onClose={close}
      />,
    ),
  );
  return { confirmed, close };
}

const input = () =>
  host.querySelector<HTMLInputElement>("[data-call-label-editor] input")!;
const saveButton = () =>
  host.querySelector<HTMLButtonElement>('button[type="submit"]')!;
const buttonNamed = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === text,
  );
const gate = () =>
  host
    .querySelector("[data-call-label-gate]")
    ?.getAttribute("data-call-label-gate") ?? null;
const type = (value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input(), value);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
const submit = () =>
  act(async () =>
    host
      .querySelector("[data-call-label-editor]")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );

it("reports a lost PATCH response as unconfirmed and confirms it by GET", async () => {
  // The server committed the rename, but the response never arrived.
  const save = vi.fn<Save>(async () => {
    throw new TypeError("Failed to fetch");
  });
  const refresh = vi.fn<Refresh>(async () => ({
    displayName: "Renewal review",
    revision: 3,
  }));
  const { confirmed, close } = await mount(save, refresh);
  await type("Renewal review");
  await submit();

  expect(host.textContent).toContain(
    "We couldn't confirm whether the name was saved",
  );
  expect(host.textContent).not.toContain("wasn't saved");
  expect(gate()).toBe("uncertain");
  expect(input().value).toBe("Renewal review");
  // No second PATCH until the status is checked.
  expect(saveButton().disabled).toBe(true);
  await submit();
  expect(buttonNamed("Clear name")?.disabled).toBe(true);
  expect(save).toHaveBeenCalledOnce();

  await act(async () => buttonNamed("Check saved name")!.click());
  expect(refresh).toHaveBeenCalledOnce();
  // The GET shows the change landed: confirmed from the server, editor closes.
  expect(confirmed).toHaveBeenCalledWith({
    displayName: "Renewal review",
    revision: 3,
  });
  expect(close).toHaveBeenCalledOnce();
  expect(save).toHaveBeenCalledOnce();
});

it("keeps a newer draft typed after an uncertain save when the check confirms the earlier one", async () => {
  const save = vi
    .fn<Save>()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce({ displayName: "Renewal review v2", revision: 4 });
  // The first attempt did land on the server.
  const refresh = vi.fn<Refresh>(async () => ({
    displayName: "Renewal review",
    revision: 3,
  }));
  const { confirmed, close } = await mount(save, refresh);
  await type("Renewal review");
  await submit();
  expect(gate()).toBe("uncertain");

  // The reader keeps typing while the outcome is unknown.
  await type("Renewal review v2");
  await act(async () => buttonNamed("Check saved name")!.click());

  // The server-confirmed earlier value is applied, but the newer text stays.
  expect(confirmed).toHaveBeenCalledWith({
    displayName: "Renewal review",
    revision: 3,
  });
  expect(close).not.toHaveBeenCalled();
  expect(input().value).toBe("Renewal review v2");
  expect(host.textContent).toContain(
    "Your earlier change is the saved name; your newer text isn't saved yet.",
  );
  expect(gate()).toBeNull();
  expect(saveButton().disabled).toBe(false);

  // Saving the newer text uses the revision the check returned.
  await submit();
  expect(save.mock.calls.map(([name, revision]) => [name, revision])).toEqual([
    ["Renewal review", 2],
    ["Renewal review v2", 3],
  ]);
  expect(close).toHaveBeenCalledOnce();
});

it("keeps text typed while the status check itself is still in flight", async () => {
  let resolveRefresh: (label: CallLabel) => void = () => {};
  const save = vi.fn<Save>(async () => {
    throw new AcquisitionError(502);
  });
  const refresh = vi.fn<Refresh>(
    () =>
      new Promise<CallLabel>((resolve) => {
        resolveRefresh = resolve;
      }),
  );
  const { close } = await mount(save, refresh);
  await type("Budget call");
  await submit();
  await act(async () => buttonNamed("Check saved name")!.click());
  // Still checking: the reader edits again before the read returns.
  await type("Budget call, part 2");
  await act(async () =>
    resolveRefresh({ displayName: "Budget call", revision: 3 }),
  );

  expect(close).not.toHaveBeenCalled();
  expect(input().value).toBe("Budget call, part 2");
  expect(host.textContent).toContain("your newer text isn't saved yet");
});

it("treats a malformed confirmation as unconfirmed; a GET showing no change allows a fresh save", async () => {
  const save = vi
    .fn<Save>()
    .mockRejectedValueOnce(new CallLabelContractError("call_label_invalid"))
    .mockResolvedValueOnce({ displayName: "Mine", revision: 5 });
  const refresh = vi.fn<Refresh>(async () => ({
    displayName: "Theirs",
    revision: 4,
  }));
  const { confirmed, close } = await mount(save, refresh);
  await type("Mine");
  await submit();
  expect(gate()).toBe("uncertain");

  await act(async () => buttonNamed("Check saved name")!.click());
  expect(host.textContent).toContain("Current name: Theirs");
  // A concurrent writer may have replaced an earlier save that did land, so
  // the copy states only that it is not the current saved name.
  expect(host.textContent).toContain(
    "Your earlier change is not the current saved name",
  );
  expect(host.textContent).not.toContain("was not saved");
  expect(gate()).toBeNull();
  expect(input().value).toBe("Mine");
  expect(close).not.toHaveBeenCalled();

  await submit();
  // The retry is issued against the revision the GET returned.
  expect(save.mock.calls.map(([name, revision]) => [name, revision])).toEqual([
    ["Mine", 2],
    ["Mine", 4],
  ]);
  expect(confirmed).toHaveBeenLastCalledWith({
    displayName: "Mine",
    revision: 5,
  });
  expect(close).toHaveBeenCalledOnce();
});

it("treats server errors as unconfirmed and keeps the block if the check fails", async () => {
  const save = vi.fn<Save>(async () => {
    throw new AcquisitionError(503);
  });
  const refresh = vi.fn<Refresh>(async () => {
    throw new TypeError("offline");
  });
  await mount(save, refresh);
  await type("Pricing call");
  await submit();
  expect(gate()).toBe("uncertain");
  await act(async () => buttonNamed("Check saved name")!.click());
  expect(host.textContent).toContain("The saved name couldn't be checked");
  expect(gate()).toBe("uncertain");
  expect(saveButton().disabled).toBe(true);
  expect(input().value).toBe("Pricing call");
  expect(save).toHaveBeenCalledOnce();
});

it("requires a fresh revision after a conflict before saving again", async () => {
  const save = vi
    .fn<Save>()
    .mockRejectedValueOnce(new AcquisitionError(409))
    .mockResolvedValueOnce({ displayName: "Mine", revision: 4 });
  const refresh = vi.fn<Refresh>(async () => ({
    displayName: "Theirs",
    revision: 3,
  }));
  await mount(save, refresh);
  await type("Mine");
  await submit();
  expect(gate()).toBe("conflict");
  expect(saveButton().disabled).toBe(true);
  await submit();
  expect(save).toHaveBeenCalledOnce();

  await act(async () => buttonNamed("Refresh name")!.click());
  expect(host.textContent).toContain("Current name: Theirs");
  expect(saveButton().disabled).toBe(false);
  await submit();
  expect(save.mock.calls[1].slice(0, 2)).toEqual(["Mine", 3]);
});

it("never turns a missing label contract into an unnamed, writable call", async () => {
  const save = vi.fn<Save>(async () => {
    throw new AcquisitionError(409);
  });
  // An older server: the refresh read carries no label fields at all.
  const refresh = vi.fn<Refresh>(async () => null);
  const { confirmed } = await mount(save, refresh);
  await type("Mine");
  await submit();
  await act(async () => buttonNamed("Refresh name")!.click());

  expect(gate()).toBe("unavailable");
  expect(host.textContent).toContain("Call names aren't available");
  expect(host.textContent).not.toContain("Current name: none");
  expect(host.textContent).not.toContain("no name saved");
  expect(confirmed).not.toHaveBeenCalled();
  expect(saveButton().disabled).toBe(true);
  expect(buttonNamed("Refresh name")).toBeUndefined();
  expect(buttonNamed("Clear name")).toBeUndefined();
  await submit();
  expect(save).toHaveBeenCalledOnce();
  expect(input().value).toBe("Mine");
});

it("keeps a definite rejection as a plain, retryable failure", async () => {
  const save = vi.fn<Save>(async () => {
    throw new AcquisitionError(422);
  });
  await mount(save, vi.fn<Refresh>());
  await type("x");
  await submit();
  expect(host.textContent).toContain("The server didn't accept this name");
  expect(gate()).toBeNull();
  expect(saveButton().disabled).toBe(false);
});
