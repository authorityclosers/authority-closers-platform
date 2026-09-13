import { renderToStaticMarkup } from "react-dom/server";
import { Window } from "happy-dom";
import { afterEach, expect, it, vi } from "vitest";

import { LearnerShell } from "./site-shell";
import { usePracticeNavigationAvailability } from "./practice-availability";

vi.mock("./practice-availability", () => ({
  usePracticeNavigationAvailability: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

it("makes Sales Xray discoverable and current in signed-in navigation", () => {
  vi.mocked(usePracticeNavigationAvailability).mockReturnValue(false);

  const markup = renderToStaticMarkup(<LearnerShell current="sales-xray" />);
  const window = new Window();
  window.document.body.innerHTML = markup;
  const navigation = window.document.querySelector(
    'nav[aria-label="Learner workspace sections"]',
  );
  expect(navigation).not.toBeNull();
  expect(navigation?.querySelectorAll('a[href="/sales-xray"]')).toHaveLength(1);
  expect(
    navigation
      ?.querySelector('a[href="/sales-xray"]')
      ?.getAttribute("aria-current"),
  ).toBe("page");

  expect(markup).toContain('href="/sales-xray"');
  expect(markup).toContain("Sales Xray");
  expect(markup).toContain('aria-current="page"');
  expect(markup).not.toContain('href="https://');
  expect(usePracticeNavigationAvailability).toHaveBeenCalledWith("sales-xray");
});
