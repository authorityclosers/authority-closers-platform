// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notices: [] as Array<{
    id: string;
    title: string;
    action?: { run: () => void };
  }>,
  dismissed: [] as string[],
}));
vi.mock("../notice-center", () => ({
  notify: (notice: {
    id: string;
    title: string;
    action?: { run: () => void };
  }) => mocks.notices.push(notice),
  dismissNotice: (id: string) => mocks.dismissed.push(id),
}));

const { HomeLoadWatch, resetHomeReads, useHomeRead } = await import(
  "./home-load"
);

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let answers: Array<() => Promise<number>>;

function Figure() {
  const { value, failed } = useHomeRead("figure", () => answers.shift()!());
  return (
    <p data-failed={failed || undefined}>{value === null ? "…" : value}</p>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  resetHomeReads();
  mocks.notices.length = 0;
  mocks.dismissed.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

// Persona QA, 31 Oct 2026: Home sat on grey boxes for ever when /v1 failed.
it("keeps the last good answer, says so after 8 s, and reads again on Retry", async () => {
  answers = [async () => 12];
  await act(async () =>
    root.render(
      <>
        <HomeLoadWatch />
        <Figure />
      </>,
    ),
  );
  expect(host.textContent).toBe("12");
  // A second mount whose read fails shows the last good answer, not a box.
  await act(async () => root.render(<HomeLoadWatch />));
  answers = [async () => Promise.reject(new Error("offline")), async () => 15];
  await act(async () =>
    root.render(
      <>
        <HomeLoadWatch />
        <Figure />
      </>,
    ),
  );
  expect(host.textContent).toBe("12");
  expect(host.querySelector("[data-failed]")).not.toBeNull();
  // Nothing at once: the card comes after 8 s.
  expect(mocks.notices).toEqual([]);
  await act(async () => vi.advanceTimersByTime(8_000));
  const card = mocks.notices.at(-1)!;
  expect(card.title).toBe("Couldn't load");
  // Retry reads again; the card goes once all is in.
  await act(async () => card.action!.run());
  expect(host.textContent).toBe("15");
  expect(mocks.dismissed).toContain("home-load");
});
