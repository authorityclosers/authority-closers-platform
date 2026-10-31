// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));

import { REPORT_PROBLEM_EVENT } from "./open";
import { ReportButton, setReportButtonHidden } from "./report-button";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The reporter in plain sight on a computer (orchestrator for the owner,
// 31 Oct 2026): a corner button that opens it, and that anyone may hide.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notify.mockReset();
  setReportButtonHidden(false);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  setReportButtonHidden(false);
});

const button = (label: string) =>
  host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

it("opens the reporter, stays out of its own picture, and hides until shown again", async () => {
  const opened = vi.fn();
  window.addEventListener(REPORT_PROBLEM_EVENT, opened);
  try {
    await act(async () => root.render(<ReportButton />));
    expect(
      button("Report a problem")!.closest("[data-capture-skip]"),
    ).not.toBeNull();
    await act(async () => button("Report a problem")!.click());
    expect(opened).toHaveBeenCalledTimes(1);

    await act(async () => button("Hide the report button")!.click());
    expect(button("Report a problem")).toBeNull();
    expect(window.localStorage.getItem("sx.report-button.hidden")).toBe("1");
    const notice = notify.mock.calls[0][0];
    expect(notice).toMatchObject({
      tone: "info",
      title: "Report button hidden",
      message: "Report a problem stays in your profile menu.",
    });
    await act(async () => notice.action.run());
    expect(button("Report a problem")).not.toBeNull();
    expect(window.localStorage.getItem("sx.report-button.hidden")).toBeNull();
  } finally {
    window.removeEventListener(REPORT_PROBLEM_EVENT, opened);
  }
});
