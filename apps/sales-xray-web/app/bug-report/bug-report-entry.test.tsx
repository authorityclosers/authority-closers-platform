import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { NoticeCenter, dismissNotice, notify } from "../notice-center";
import { SettingsMenu } from "../shell/settings-menu";
import {
  installReportShortcut,
  REPORT_PROBLEM_EVENT,
  reporterMounted,
  type ReportAbout,
} from "./open";
import { copyScreen } from "./capture";
import { clearRecentErrors, recentErrors } from "./recent-errors";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const opened: Array<ReportAbout | null> = [];
const listen = (event: Event) =>
  opened.push((event as CustomEvent<ReportAbout | null>).detail);

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.removeEventListener(REPORT_PROBLEM_EVENT, listen);
  opened.length = 0;
  clearRecentErrors();
  vi.unstubAllGlobals();
});

async function render(node: ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  window.addEventListener(REPORT_PROBLEM_EVENT, listen);
  await act(async () => root.render(node));
}

function button(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );
}

it("You → Report a problem closes the menu and opens the reporter", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  const onClose = vi.fn();
  await render(
    <SettingsMenu
      open
      anchorRef={{ current: document.createElement("button") }}
      onClose={onClose}
      name="Fictional User"
      email="fictional@example.test"
      allowance={null}
    />,
  );
  const row = button("Report a problem");
  expect(row).toBeDefined();
  await act(async () => row!.click());
  expect(onClose).toHaveBeenCalled();
  expect(opened).toEqual([null]);
});

it("an error card offers Report only while the reporter is in the app", async () => {
  await render(<NoticeCenter />);
  await act(async () =>
    notify({
      id: "save-failed",
      tone: "error",
      title: "Couldn't save the note",
      message: "Try again.",
      reference: "req-77aa1234",
    }),
  );
  // Recorded for the next report, whatever happens to the card.
  expect(recentErrors().at(-1)).toMatchObject({
    kind: "notice",
    message: "Couldn't save the note: Try again.",
    reference: "req-77aa1234",
  });
  expect(button("Report")).toBeUndefined();

  let unmount = () => {};
  await act(async () => {
    unmount = reporterMounted();
  });
  expect(button("Report")).toBeDefined();
  await act(async () => button("Report")!.click());
  expect(opened).toEqual([
    { title: "Couldn't save the note", reference: "req-77aa1234" },
  ]);

  // The reporter's own failure card never offers Report.
  await act(async () =>
    notify({
      id: "bug-report-failed",
      tone: "error",
      title: "Your report didn't go",
      noReport: true,
    }),
  );
  expect(button("Report")).toBeUndefined();
  await act(async () => {
    dismissNotice("bug-report-failed");
    unmount();
  });
});

// #5 (owner, 26 Oct 2026): with a menu open, the computer's shortcut still reports, and
// the menu stays open for the report's picture; the menu shows the shortcut.
it("opens a menu, then reports from it with Ctrl B", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(pointer: fine)",
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  const onClose = vi.fn();
  const uninstall = installReportShortcut();
  await render(
    <SettingsMenu
      open
      anchorRef={{ current: document.createElement("button") }}
      onClose={onClose}
      name="Fictional User"
      email="fictional@example.test"
      allowance={null}
    />,
  );
  const row = button("Report a problem");
  expect(row?.getAttribute("aria-keyshortcuts")).toBe("Control+B");
  expect(
    row?.querySelector("[data-shortcut]")?.getAttribute("data-shortcut"),
  ).toBe("Ctrl B");
  // A menu that keeps its own keys cannot swallow the shortcut.
  const menu = row!.closest("div") as HTMLElement;
  menu.addEventListener("keydown", (event) => event.stopPropagation());
  row!.focus();
  await act(async () => {
    row!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "b", ctrlKey: true, bubbles: true }),
    );
  });
  expect(opened).toEqual([null]);
  expect(onClose).not.toHaveBeenCalled();
  uninstall();
});

// Dev #2 (owner, 26 Oct 2026): with a side panel open, the picture left the panel out.
// Every open layer is in it (side panels, sheets, menus); the reporter's own sheet is not,
// and a key shown once reads as a marker.
it("reports from a screen with a side panel open: the picture keeps the panel", async () => {
  await render(<main>Organisation · Connections</main>);
  const panel = document.createElement("dialog");
  panel.innerHTML =
    "<h2>Connected apps</h2><code>Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7cDe0fGh</code>";
  const reporter = document.createElement("dialog");
  reporter.innerHTML =
    "<form data-bug-reporter><p>Tell us what went wrong</p></form>";
  document.body.append(panel, reporter);
  panel.setAttribute("open", "");
  reporter.setAttribute("open", "");
  const copy = await copyScreen();
  panel.remove();
  reporter.remove();
  expect(copy).not.toBeNull();
  const text = copy!.textContent ?? "";
  expect(text).toContain("Organisation · Connections");
  expect(text).toContain("Connected apps");
  expect(text).not.toContain("Tell us what went wrong");
  expect(text).not.toContain("Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7cDe0fGh");
  expect(text).toContain("[long]");
});
