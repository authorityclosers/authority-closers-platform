import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { ReflexShell } from "../shell/reflex-shell";
import { PublicShell } from "./public-shell";
vi.mock("next/navigation", () => ({
  usePathname: () => "/learning",
  useRouter: () => ({ prefetch: vi.fn() }),
}));
it.each([false, true])(
  "Reflex places follow the server's Practice gate=%s",
  (enabled) => {
    const markup = renderToStaticMarkup(
      <ReflexShell practiceEnabled={enabled}>
        <p>Content</p>
      </ReflexShell>,
    );
    expect(markup.includes('href="/practice"')).toBe(enabled);
    expect(markup).toContain("Learn");
    expect(markup).not.toContain('href="/sales-xray"');
  },
);
it("keeps the public Reflex entry free of embedded studio navigation", () => {
  const markup = renderToStaticMarkup(<PublicShell />);
  expect(markup).toContain("Reflex");
  expect(markup).toContain("Sales training by Authority Closers");
  expect(markup).not.toContain('href="/sales-xray"');
});
