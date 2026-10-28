import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { expect, it, vi } from "vitest";
import { ReflexShell } from "../shell/reflex-shell";
import { salesXrayForHost } from "../shell/places";
vi.mock("next/navigation", () => ({
  usePathname: () => "/learning",
  useRouter: () => ({ prefetch: vi.fn() }),
}));

it("keeps the embedded Sales X-Ray area out of Reflex navigation", () => {
  const markup = renderToStaticMarkup(
    <ReflexShell>
      <p>Content</p>
    </ReflexShell>,
  );
  expect(markup).not.toContain('href="/sales-xray"');
  expect(markup).not.toContain("Assigned review");
  expect(markup).toContain('href="/learning"');
  expect(markup).toContain('aria-current="page"');
  expect(salesXrayForHost("learner.authorityclosers.com")).toBe(
    "https://salesxray.authorityclosers.com",
  );
});
it("keeps reviewer navigation out of the learner shell and preserves the embedded route", () => {
  const shell = readFileSync(
    new URL("../shell/reflex-shell.tsx", import.meta.url),
    "utf8",
  );
  const embed = readFileSync(
    new URL("../sales-xray/sales-xray-shell.tsx", import.meta.url),
    "utf8",
  );
  expect(shell).not.toContain("requestReviewNavigation");
  expect(embed).toContain("<ReflexShell>");
  expect(embed).toContain('variant="embedded"');
});
