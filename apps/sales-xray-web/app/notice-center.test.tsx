import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { dismissNotice, NoticeCenter, notify } from "./notice-center";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<NoticeCenter />));
});
afterEach(async () => {
  await act(async () => {
    dismissNotice("fictional");
    root.unmount();
  });
  host.remove();
});
const close = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="Dismiss"]')!;
it("retains the card until permanent dismissal is acknowledged", async () => {
  let resolve!: () => void;
  const onDismiss = vi.fn(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      onDismiss,
    }),
  );
  await act(async () => close().click());
  expect(onDismiss).toHaveBeenCalledTimes(1);
  expect(close().disabled).toBe(true);
  expect(host.textContent).toContain("Fictional update");
  await act(async () => resolve());
  expect(host.textContent).not.toContain("Fictional update");
});
it("dismisses from a worded button the same way as the X", async () => {
  const onDismiss = vi.fn(async () => {});
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      dismissLabel: "Later",
      onDismiss,
    }),
  );
  const later = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Later",
  )!;
  await act(async () => later.click());
  expect(onDismiss).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain("Fictional update");
});
it("keeps a failed acknowledgement actionable and retries", async () => {
  const onDismiss = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(undefined);
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      onDismiss,
    }),
  );
  await act(async () => close().click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Try again",
  );
  expect(close().disabled).toBe(false);
  await act(async () => close().click());
  expect(onDismiss).toHaveBeenCalledTimes(2);
  expect(host.textContent).not.toContain("Fictional update");
});
it("preserves ordinary notice actions and avoids removing a permanent card on navigation", async () => {
  const run = vi.fn();
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      timeout: 0,
      onDismiss: async () => {},
      action: { label: "Open", run },
    }),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(run).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Fictional update");
  await act(async () =>
    notify({
      id: "fictional",
      tone: "error",
      title: "Ordinary notice",
      action: { label: "Retry", run },
    }),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(host.textContent).not.toContain("Ordinary notice");
});
it("shows at most two cards, the older ones under +N more", async () => {
  // Owner via the orchestrator, 31 Oct 2026: at most two show, in one corner.
  const ids = ["first", "second", "third", "fourth"];
  try {
    for (const id of ids)
      await act(async () =>
        notify({ id, tone: "info", title: `Fictional ${id} update` }),
      );
    const titles = () =>
      ids.filter((id) => host.textContent?.includes(`Fictional ${id} update`));
    expect(titles()).toEqual(["third", "fourth"]);
    const more = () =>
      [...host.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
        /^\+\d+ more$|^Show fewer$/.test(button.textContent ?? ""),
      );
    expect(more()?.textContent).toBe("+2 more");
    await act(async () => more()!.click());
    expect(titles()).toEqual(ids);
    expect(more()?.textContent).toBe("Show fewer");
    await act(async () => more()!.click());
    expect(titles()).toEqual(["third", "fourth"]);
    await act(async () => {
      dismissNotice("first");
      dismissNotice("second");
    });
    expect(more()).toBeUndefined();
  } finally {
    await act(async () => ids.forEach((id) => dismissNotice(id)));
  }
});
