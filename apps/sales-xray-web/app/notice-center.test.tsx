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
