import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { NoticeCenter, dismissNotice, notify } from "../notice-center";
import { SettingsMenu } from "../shell/settings-menu";
import {
  REPORT_PROBLEM_EVENT,
  reporterMounted,
  type ReportAbout,
} from "./open";
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
