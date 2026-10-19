import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import DevelopersPage from "./page";

it("documents every way to connect, generically", () => {
  const html = renderToStaticMarkup(<DevelopersPage />);
  for (const anchor of [
    "keys",
    "api",
    "webhooks",
    "handover",
    "connect",
    "cli",
  ])
    expect(html).toContain(`id="${anchor}"`);
  expect(html).toContain("https://salesxray.authorityclosers.com/v1/api");
  expect(html).toContain("X-SX-Signature");
  expect(html).toContain("code_challenge_method=S256");
  expect(html).toContain('href="/developers/sx.py"');
  expect(html).toContain("sxk_live_");
  // Generic for every organisation: no customer or partner product names.
  expect(html).not.toMatch(/wise\s*life|pulse/i);
});
