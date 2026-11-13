// @vitest-environment happy-dom
import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import type { LeadEvent } from "./leads-client";
import { History } from "./lead-sheet";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const note = (day: number): LeadEvent =>
  ({
    kind: "note",
    at: `2026-11-${String(day).padStart(2, "0")}T09:30:00Z`,
    actor_name: "Kavya Fictional",
    note: `Note ${day}`,
  }) as LeadEvent;
// Newest first, as the lead's history comes.
const events = [9, 8, 7, 6, 5].map(note);
const rows = () => host.querySelectorAll('li[data-kind="note"]').length;
const more = () =>
  [...host.querySelectorAll("button")].find((button) =>
    /^See (more|less)$/.test(button.textContent ?? ""),
  );

// Dipak's bug 198 (10 Nov 2026): the history made the lead page look full. The
// three newest show, then See more opens the rest.
it("shows the three newest, then See more opens all of them", async () => {
  await act(async () => root.render(<History events={events} shown={3} />));
  expect(rows()).toBe(3);
  expect(host.textContent).toContain("Note 9");
  expect(host.textContent).not.toContain("Note 6");
  expect(more()?.textContent).toBe("See more");
  expect(more()?.getAttribute("aria-expanded")).toBe("false");
  await act(async () => more()?.click());
  expect(rows()).toBe(5);
  expect(more()?.textContent).toBe("See less");
  await act(async () => more()?.click());
  expect(rows()).toBe(3);
});

it("has no See more with three or fewer, and opens to a line it's asked to show", async () => {
  await act(async () =>
    root.render(<History events={events.slice(0, 3)} shown={3} />),
  );
  expect(rows()).toBe(3);
  expect(more()).toBeUndefined();
  // Opened from My work at an older line: everything shows, so it can be lit.
  await act(async () =>
    root.render(<History events={events} shown={3} focusAt={events[4].at} />),
  );
  expect(rows()).toBe(5);
});
