// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usePracticeNavigationAvailability } from "./practice-availability";
import { loadPracticeNavigationAvailability } from "../lib/practice-navigation";
import { ReflexShell } from "../shell/reflex-shell";
vi.mock("next/navigation", () => ({
  usePathname: () => "/practice",
  useRouter: () => ({ prefetch: vi.fn() }),
}));

vi.mock("../lib/practice-navigation", () => ({
  loadPracticeNavigationAvailability: vi.fn(),
}));
vi.mock("../lib/learner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/learner-api")>()),
  createLearnerApi: () => ({
    request: async () => {
      throw new Error("Notifications unavailable in navigation test");
    },
    me: async () => {
      throw new Error("Identity unavailable in navigation test");
    },
    profileAvatar: async () => {
      throw new Error("Avatar unavailable in navigation test");
    },
  }),
}));
const load = vi.mocked(loadPracticeNavigationAvailability);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
let unmounted = false;
function Probe({ scope = "home" }: { scope?: string }) {
  const available = usePracticeNavigationAvailability(scope);
  return (
    <nav>{available ? <a href="/practice">Practice Arcade</a> : null}</nav>
  );
}
beforeEach(() => {
  load.mockReset().mockResolvedValue(false);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
it("does not render a speculative server-side link", () => {
  expect(renderToStaticMarkup(<Probe />)).not.toContain("/practice");
  expect(load).not.toHaveBeenCalled();
});
it("reveals only confirmed availability, and removes it after fresh focus denial", async () => {
  load.mockResolvedValueOnce(true).mockResolvedValue(false);
  await act(async () => root.render(<Probe />));
  expect(container.querySelector("a")?.textContent).toBe("Practice Arcade");
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(container.querySelector("a")).toBeNull();
  expect(load).toHaveBeenCalledTimes(2);
});
it("uses the same server-provided Practice gate on the Reflex rail and phone bar", async () => {
  await act(async () =>
    root.render(
      <ReflexShell practiceEnabled>
        <p>Content</p>
      </ReflexShell>,
    ),
  );
  expect(
    container.querySelector(
      'nav[aria-label="Reflex places"] a[href="/practice"]',
    ),
  ).not.toBeNull();
  const mobile = container.querySelector(
    'nav[aria-label="Phone places"] a[href="/practice"]',
  );
  expect(mobile?.textContent).toBe("Practice");
  expect(mobile?.getAttribute("aria-current")).toBe("page");
  await act(async () =>
    root.render(
      <ReflexShell practiceEnabled={false}>
        <p>Content</p>
      </ReflexShell>,
    ),
  );
  expect(container.querySelector('a[href="/practice"]')).toBeNull();
  expect(
    container.querySelector(
      'nav[aria-label="Phone places"] a[href="/learning"]',
    ),
  ).not.toBeNull();
});

it("cancels old scope reads and ignores late results", async () => {
  let finishOld: ((value: boolean) => void) | undefined;
  load
    .mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockResolvedValue(false);
  await act(async () => root.render(<Probe scope="old" />));
  const oldSignal = load.mock.calls[0][0];
  await act(async () => root.render(<Probe scope="new" />));
  expect(oldSignal.aborted).toBe(true);
  await act(async () => finishOld?.(true));
  expect(container.querySelector("a")).toBeNull();
});
it("aborts pending admission and removes refresh listeners on unmount", async () => {
  load.mockImplementation(() => new Promise<boolean>(() => undefined));
  await act(async () => root.render(<Probe />));
  const signal = load.mock.calls[0][0];
  await act(async () => root.unmount());
  unmounted = true;
  expect(signal.aborted).toBe(true);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(load).toHaveBeenCalledOnce();
});
