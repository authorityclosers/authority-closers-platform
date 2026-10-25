// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

const haptic = vi.fn();
vi.mock("../ui/haptics", () => ({ haptic: (kind: string) => haptic(kind) }));

import { AlertHost, clearAlert } from "../ui/alerts";
import { DueSoonWatch, readSoon, showSoon, type SoonItem } from "./due-soon";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ITEM: SoonItem = {
  lead_id: "6f1c3b0e-8a52-4d0e-9a7c-6d2b1f7a9e31",
  lead_name: "Priya Sample",
  what: "follow_up",
  at: "2026-10-26T05:10:00+00:00",
  minutes: 40,
  title: null,
  words: "Priya Sample: follow-up in 40 min",
};

let root: Root;
let host: HTMLDivElement;
const fetchMock = vi.fn();

function answer(status: number, body: unknown) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

beforeEach(async () => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () =>
    clearAlert(`due-soon:${ITEM.lead_id}:follow_up:${ITEM.at}`),
  );
  await act(async () => root.unmount());
  host.remove();
  haptic.mockClear();
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

// Owner, 25 Oct 2026 (workflow 12): a red banner up top naming the lead, with
// the urgent haptic, opening the lead; once per follow-up.
it("raises the red banner once per follow-up, opening the lead", async () => {
  answer(200, { item: ITEM, generated_at: "2026-10-26T04:30:00Z" });
  await act(async () =>
    root.render(
      <>
        <AlertHost />
        <DueSoonWatch live />
      </>,
    ),
  );
  for (let flush = 0; flush < 6; flush += 1) {
    await act(async () => Promise.resolve());
  }
  const banner = host.querySelector('[role="status"]');
  expect(banner?.getAttribute("data-emphasis")).toBe("urgent");
  expect(banner?.textContent).toContain("Priya Sample: follow-up in 40 min");
  expect(banner?.querySelector("a")?.getAttribute("href")).toBe(
    `/leads?lead=${ITEM.lead_id}`,
  );
  expect(haptic).toHaveBeenCalledWith("urgent");
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/v1/lead-desk/soon");

  // The same follow-up again (the next read, a refresh) raises nothing new.
  haptic.mockClear();
  expect(showSoon(ITEM)).toBe(false);
  expect(haptic).not.toHaveBeenCalled();
});

it("reads nothing when not live, and stops where leads don't apply", async () => {
  await act(async () => root.render(<DueSoonWatch live={false} />));
  expect(fetchMock).not.toHaveBeenCalled();
  answer(403, { detail: "Leads work inside an organisation workspace." });
  expect(await readSoon()).toBe("off");
  answer(200, { item: null, generated_at: "2026-10-26T04:30:00Z" });
  expect(await readSoon()).toBeNull();
  fetchMock.mockRejectedValue(new Error("offline"));
  expect(await readSoon()).toBeNull();
});
