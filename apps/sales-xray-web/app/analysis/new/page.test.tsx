// @vitest-environment happy-dom
import { isValidElement } from "react";
import { expect, it, vi } from "vitest";

vi.mock("../../acquisition-studio", () => ({
  AcquisitionStudio: () => null,
}));

import { AcquisitionStudio } from "../../acquisition-studio";
import NewAnalysisPage from "./page";

// The test robot, a9e8d053 (1 Nov 2026): on a phone, "<name> is your lead
// now" sat in the corner and lifted the first-call guide over Choose a file.
// New analysis asks the studio for the page's notice dock, as Leads has one:
// its notices are one line at the top of the studio's own scroller.
it("asks the studio for the page's notice dock", async () => {
  const page = await NewAnalysisPage({ searchParams: Promise.resolve({}) });
  expect(isValidElement(page)).toBe(true);
  expect(page.type).toBe(AcquisitionStudio);
  expect(page.props).toMatchObject({ noticeDock: true });
});
