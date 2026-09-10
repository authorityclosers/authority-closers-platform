import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { LearnerShell } from "./site-shell";
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
    expect(usePracticeNavigationAvailability).toHaveBeenCalledWith("learning");
  },
);
