import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { rowKeyStep, useRowKeys, type RowKeyActions } from "./row-keys";

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

function Rows({ actions }: { actions: RowKeyActions }) {
  const list = useRef<HTMLUListElement>(null);
  useRowKeys(list, actions);
  return (
    <>
      <input aria-label="Search" />
      <ul ref={list}>
        {["a", "b", "c"].map((id) => (
          <li key={id} data-row-key={id}>
            Lead {id}
          </li>
        ))}
      </ul>
    </>
  );
}

const press = async (key: string, target: Element = document.body) =>
  act(async () => {
    target.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });

it("names the step each key asks for", () => {
  expect(
    ["j", "ArrowDown", "k", "ArrowUp", "Enter", "e", "c", "L", "x"].map(
      rowKeyStep,
    ),
  ).toEqual([
    "next",
    "next",
    "previous",
    "previous",
    "open",
    "open",
    "call",
    "log",
    null,
  ]);
});

it("moves through the rows with J and K and acts on the focused one", async () => {
  const actions = { open: vi.fn(), call: vi.fn(), log: vi.fn() };
  await act(async () => root.render(<Rows actions={actions} />));
  // Rows are laid out for the hook's on-screen check.
  host.querySelector("ul")!.getClientRects = () =>
    [{}] as unknown as DOMRectList;
  const focused = () =>
    (document.activeElement as HTMLElement | null)?.dataset.rowKey;
  await press("j");
  expect(focused()).toBe("a");
  await press("j", document.activeElement!);
  await press("j", document.activeElement!);
  await press("j", document.activeElement!);
  expect(focused()).toBe("c");
  await press("k", document.activeElement!);
  expect(focused()).toBe("b");
  await press("Enter", document.activeElement!);
  await press("c", document.activeElement!);
  await press("l", document.activeElement!);
  expect(actions.open).toHaveBeenCalledWith("b");
  expect(actions.call).toHaveBeenCalledWith("b");
  expect(actions.log).toHaveBeenCalledWith("b");
});

it("leaves keys alone while typing, with a modifier, or under an overlay", async () => {
  const actions = { open: vi.fn(), call: vi.fn() };
  await act(async () => root.render(<Rows actions={actions} />));
  host.querySelector("ul")!.getClientRects = () =>
    [{}] as unknown as DOMRectList;
  await press("j", host.querySelector("input")!);
  expect(document.activeElement?.tagName).not.toBe("LI");
  await act(async () => {
    document.body.dispatchEvent(
      new KeyboardEvent("keydown", { key: "j", ctrlKey: true, bubbles: true }),
    );
  });
  expect(document.activeElement?.tagName).not.toBe("LI");
  const dialog = document.createElement("dialog");
  dialog.setAttribute("open", "");
  document.body.append(dialog);
  await press("j");
  expect(document.activeElement?.tagName).not.toBe("LI");
  dialog.remove();
  // Not on a row: C and Enter do nothing.
  await press("c");
  expect(actions.call).not.toHaveBeenCalled();
});
