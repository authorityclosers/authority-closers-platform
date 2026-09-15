import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { LearnerShell, PublicShell } from "./site-shell";
import { getDefaultCommandPaletteItems } from "./learner-sidebar/command-palette";
import { usePracticeNavigationAvailability } from "./practice-availability";

vi.mock("./practice-availability", () => ({
  usePracticeNavigationAvailability: vi.fn(),
}));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});
it.each([false, true])(
  "shared navigation follows actual runtime admission=%s in production",
  (enabled) => {
    vi.stubEnv("NODE_ENV", "production");
    vi.mocked(usePracticeNavigationAvailability).mockReturnValue(enabled);
    const markup = renderToStaticMarkup(<LearnerShell current="learning" />);
    expect(markup.includes('href="/practice"')).toBe(enabled);
    expect(markup).toContain("My Learning");
    expect(markup).toContain('href="/sales-xray"');
    expect(usePracticeNavigationAvailability).toHaveBeenCalledWith("learning");
  },
);

it("provides a public and keyboard-search entry without adding identity to the URL", () => {
  const markup = renderToStaticMarkup(<PublicShell />);
  expect(markup).toContain('href="/sales-xray"');
  const item = getDefaultCommandPaletteItems().find(
    (entry) => entry.label === "Sales Xray",
  );
  expect(item?.href).toBe("/sales-xray");
});
