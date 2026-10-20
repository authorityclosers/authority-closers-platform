import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { Sheet, SHEET_PHONE_QUERY } from "./sheet";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

let phone = true;
beforeEach(() => {
  phone = true;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === SHEET_PHONE_QUERY ? phone : false,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
});
afterEach(() => {
  document.body.innerHTML = "";
});

function Host({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <Sheet
        open={open}
        title="Account"
        description="Signed in"
        onClose={() => {
          onClose();
          setOpen(false);
        }}
      >
        <p>Sheet body</p>
      </Sheet>
    </>
  );
}

async function mount(onClose?: () => void) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Host onClose={onClose} />));
  const dialog = host.querySelector("dialog")!;
  return { host, root, dialog };
}

/** The sheet's panel: the box around its body. */
const panelOf = (dialog: HTMLDialogElement) =>
  [...dialog.querySelectorAll("p")]
    .find((p) => p.textContent === "Sheet body")!
    .parentElement!.parentElement!;

function touch(type: string, target: Element, y: number, at: number) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    touches: { value: type === "touchend" ? [] : [{ clientY: y }] },
    timeStamp: { value: at },
  });
  target.dispatchEvent(event);
  return event;
}

it("opens as a named modal sheet with its title, words and close button", async () => {
  const { dialog } = await mount();
  expect(dialog.open).toBe(true);
  const title = dialog.querySelector("h2")!;
  expect(dialog.getAttribute("aria-labelledby")).toBe(title.id);
  expect(title.textContent).toBe("Account");
  expect(dialog.textContent).toContain("Signed in");
  expect(dialog.textContent).toContain("Sheet body");
  expect(dialog.querySelector('button[aria-label="Close"]')).not.toBeNull();
});

it("closes from the close button, Escape and a tap on the dimmed page", async () => {
  for (const how of ["button", "escape", "scrim"] as const) {
    const onClose = vi.fn();
    const { dialog, root } = await mount(onClose);
    await act(async () => {
      if (how === "button")
        dialog.querySelector<HTMLButtonElement>('[aria-label="Close"]')!.click();
      if (how === "escape")
        dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
      if (how === "scrim")
        (dialog.firstElementChild as HTMLElement).click();
    });
    expect(onClose, how).toHaveBeenCalledOnce();
    // It slides away first, then closes.
    await vi.waitFor(() => expect(dialog.open, how).toBe(false));
    expect(dialog.textContent, how).not.toContain("Sheet body");
    await act(async () => root.unmount());
  }
});

it("follows the finger down and closes past the line", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const panel = panelOf(dialog);
  vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
    height: 600,
  } as DOMRect);
  await act(async () => {
    touch("touchstart", panel, 100, 0);
    const moving = touch("touchmove", panel, 180, 50);
    expect(moving.defaultPrevented).toBe(true);
    expect(panel.style.transform).toBe("translate3d(0, 80px, 0)");
    touch("touchmove", panel, 360, 400);
    touch("touchend", panel, 360, 420);
  });
  expect(onClose).toHaveBeenCalledOnce();
});

it("springs back from a short, slow drag and keeps the sheet", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const panel = panelOf(dialog);
  vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
    height: 600,
  } as DOMRect);
  await act(async () => {
    touch("touchstart", panel, 100, 0);
    touch("touchmove", panel, 140, 200);
    touch("touchmove", panel, 160, 400);
    touch("touchend", panel, 160, 420);
  });
  expect(onClose).not.toHaveBeenCalled();
  expect(panel.style.transform).toBe("");
  expect(dialog.open).toBe(true);
});

it("closes on a quick flick even when the drag is short", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const panel = panelOf(dialog);
  await act(async () => {
    touch("touchstart", panel, 100, 0);
    touch("touchmove", panel, 120, 10);
    touch("touchmove", panel, 170, 60);
    touch("touchend", panel, 170, 70);
  });
  expect(onClose).toHaveBeenCalledOnce();
});

it("lets a scrolled body scroll instead of closing, and never drags on computers", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const panel = panelOf(dialog);
  const body = [...dialog.querySelectorAll("p")].find(
    (p) => p.textContent === "Sheet body",
  )!.parentElement!;
  Object.defineProperties(body, {
    scrollHeight: { value: 2000 },
    clientHeight: { value: 400 },
    scrollTop: { value: 120, writable: true },
  });
  body.style.overflowY = "auto";
  await act(async () => {
    touch("touchstart", body, 100, 0);
    const scrolling = touch("touchmove", body, 300, 40);
    expect(scrolling.defaultPrevented).toBe(false);
    touch("touchend", body, 300, 50);
  });
  phone = false;
  await act(async () => {
    touch("touchstart", panel, 100, 0);
    touch("touchmove", panel, 400, 40);
    touch("touchend", panel, 400, 50);
  });
  expect(onClose).not.toHaveBeenCalled();
});

function pointer(type: string, target: Element, y: number, at: number) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    pointerType: { value: "mouse" },
    button: { value: 0 },
    pointerId: { value: 1 },
    clientY: { value: y },
    timeStamp: { value: at },
  });
  target.dispatchEvent(event);
  return event;
}

it("closes on a mouse drag from the grabber, even one big jump, without selecting text", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const panel = panelOf(dialog);
  vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
    height: 600,
  } as DOMRect);
  const grip = dialog.querySelector("[data-sheet-grip]")!;
  await act(async () => {
    const down = pointer("pointerdown", grip, 62, 0);
    // No text selection starts under a mouse drag.
    expect(down.defaultPrevented).toBe(true);
    pointer("pointerup", grip, 650, 40);
  });
  expect(onClose).toHaveBeenCalledOnce();
});

it("lets a mouse select the body's words: only the grip drags", async () => {
  const onClose = vi.fn();
  const { dialog } = await mount(onClose);
  const body = [...dialog.querySelectorAll("p")].find(
    (p) => p.textContent === "Sheet body",
  )!;
  await act(async () => {
    const down = pointer("pointerdown", body, 100, 0);
    expect(down.defaultPrevented).toBe(false);
    pointer("pointermove", body, 500, 30);
    pointer("pointerup", body, 500, 40);
  });
  expect(onClose).not.toHaveBeenCalled();
});
