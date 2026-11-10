// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const status = vi.fn(async (): Promise<{ version: string } | null> => null);
vi.mock("../leads/native-phone", () => ({ phoneStatus: () => status() }));
const notify = vi.fn();
vi.mock("../notice-center", () => ({
  notify: (...args: unknown[]) => notify(...args),
}));

import { BuildLine, buildLine } from "./build-line";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubEnv("NEXT_PUBLIC_AC_RELEASE_ID", `3b08990${"a".repeat(33)}`);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  status.mockReset();
  status.mockImplementation(async () => null);
});

async function mount() {
  await act(async () => root.render(<BuildLine />));
  await act(async () => Promise.resolve());
}

it("says the web build, and the app's version in the phone app", async () => {
  // The orchestrator, 3 Nov 2026: phone proof shows the build on screen.
  expect(buildLine("3b08990aaaaa", "1.0.84")).toBe(
    "Build 3b08990 · App 1.0.84",
  );
  expect(buildLine("v1.38.0", null)).toBe("Build v1.38.0");
  expect(buildLine(null, null)).toBe("Build dev");
  await mount();
  expect(host.textContent).toBe("Build 3b08990");
  await act(async () => root.unmount());
  root = createRoot(host);
  status.mockImplementation(async () => ({ version: "1.0.84" }));
  await mount();
  expect(host.textContent).toBe("Build 3b08990 · App 1.0.84");
});

it("names the release when the published manifest is this very build", async () => {
  // The orchestrator, 10 Nov 2026: "Version 1.53.0 · <short commit>".
  expect(buildLine("3b08990aaaaa", "1.0.99", "1.53.0")).toBe(
    "Version 1.53.0 · 3b08990 · App 1.0.99",
  );
  const manifest = (sha: string) =>
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            format: "sx-web-bundle/1",
            payload: JSON.stringify({ version: "1.53.0", sha }),
          }),
          { status: 200 },
        ),
    );
  vi.stubGlobal("fetch", manifest(`3b08990${"a".repeat(33)}`));
  await mount();
  await act(async () => Promise.resolve());
  expect(host.textContent).toBe("Version 1.53.0 · 3b08990");
  // Another build's manifest names nothing.
  await act(async () => root.unmount());
  root = createRoot(host);
  vi.stubGlobal("fetch", manifest(`9c1d2e3${"b".repeat(33)}`));
  await mount();
  await act(async () => Promise.resolve());
  expect(host.textContent).toBe("Build 3b08990");
});

it("copies the line when it is held, and says so", async () => {
  status.mockImplementation(async () => ({ version: "1.0.84" }));
  const writeText = vi.fn(async () => undefined);
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
  await mount();
  vi.useFakeTimers();
  const line = host.querySelector("p");
  await act(async () => {
    line?.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, pointerType: "touch" }),
    );
  });
  // A tap is not a hold: nothing is copied before half a second.
  await act(async () => vi.advanceTimersByTime(300));
  expect(writeText).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTime(300));
  await act(async () => Promise.resolve());
  expect(writeText).toHaveBeenCalledWith("Build 3b08990 · App 1.0.84");
  expect(host.textContent).toBe("Copied");
  await act(async () => vi.advanceTimersByTime(2100));
  expect(host.textContent).toBe("Build 3b08990 · App 1.0.84");
  expect(notify).not.toHaveBeenCalled();
});
