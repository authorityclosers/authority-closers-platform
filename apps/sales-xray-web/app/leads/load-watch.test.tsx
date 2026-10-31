import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Shown = {
  id: string;
  title: string;
  action?: { label: string; run: () => void };
};
const notices = vi.hoisted(() => ({
  shown: [] as Shown[],
  gone: [] as string[],
}));
vi.mock("../notice-center", () => ({
  notify: (notice: Shown) => notices.shown.push(notice),
  dismissNotice: (id: string) => notices.gone.push(id),
}));

const { LIST_LOAD_NOTICE, LIST_SLOW_MS, useListLoadWatch } = await import(
  "./load-watch"
);

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Props = Parameters<typeof useListLoadWatch>[0];

function Watch(props: Props) {
  useListLoadWatch(props);
  return null;
}

let host: HTMLDivElement;
let root: Root;
const onRetry = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  notices.shown.length = 0;
  notices.gone.length = 0;
  onRetry.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const show = (props: Partial<Props>) =>
  act(() =>
    root.render(
      <Watch
        question="inbound to call"
        waiting={false}
        failed={false}
        showing={false}
        onRetry={onRetry}
        {...props}
      />,
    ),
  );

it("says Couldn't load with Retry when a read still waits after 8 s (persona QA, 31 Oct 2026)", () => {
  show({ waiting: true, showing: true });
  act(() => vi.advanceTimersByTime(LIST_SLOW_MS - 1));
  expect(notices.shown).toHaveLength(0);
  act(() => vi.advanceTimersByTime(1));
  expect(notices.shown.map((notice) => [notice.id, notice.title])).toEqual([
    [LIST_LOAD_NOTICE, "Couldn't load"],
  ]);
  act(() => notices.shown[0].action?.run());
  expect(onRetry).toHaveBeenCalledTimes(1);
  expect(notices.gone).toContain(LIST_LOAD_NOTICE);
  // Retry waits afresh: still nothing after it, the card comes back 8 s on.
  act(() => vi.advanceTimersByTime(LIST_SLOW_MS));
  expect(notices.shown).toHaveLength(2);
});

it("goes once the list is in", () => {
  show({ waiting: true });
  act(() => vi.advanceTimersByTime(LIST_SLOW_MS));
  expect(notices.shown).toHaveLength(1);
  notices.gone.length = 0;
  show({ waiting: false, showing: true });
  expect(notices.gone).toEqual([LIST_LOAD_NOTICE]);
});

it("shows a failed refresh over rows at once, and leaves an empty list to its Try again", () => {
  show({ waiting: true, failed: true, showing: true });
  expect(notices.shown).toHaveLength(1);
  show({ waiting: true, failed: true, showing: false });
  act(() => vi.advanceTimersByTime(LIST_SLOW_MS));
  expect(notices.shown).toHaveLength(1);
  expect(notices.gone).toContain(LIST_LOAD_NOTICE);
});

it("a quick answer shows nothing", () => {
  show({ waiting: true });
  act(() => vi.advanceTimersByTime(300));
  show({ waiting: false, showing: true });
  act(() => vi.advanceTimersByTime(LIST_SLOW_MS));
  expect(notices.shown).toHaveLength(0);
});
