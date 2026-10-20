// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));

import DevelopersPage from "./page";
import { ENDPOINTS, ERRORS } from "./reference";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("documents every way to connect, generically", () => {
  const html = renderToStaticMarkup(<DevelopersPage />);
  for (const anchor of [
    "start",
    "keys",
    "connect",
    "api",
    ...ENDPOINTS.map((item) => item.id),
    "webhooks",
    "mcp",
    "cli",
    "handover",
    "limits",
  ])
    expect(html).toContain(`id="${anchor}"`);
  expect(html).toContain("https://salesxray.authorityclosers.com/v1/api");
  expect(html).toContain("X-SX-Signature");
  expect(html).toContain("code_challenge_method=S256");
  expect(html).toContain('href="/developers/sx.py"');
  expect(html).toContain("sxk_live_");
  expect(html).toContain('href="/settings/developers"');
  // The remote MCP server and apps that register themselves (0370eb5a).
  expect(html).toContain("https://salesxray.authorityclosers.com/v1/mcp");
  expect(html).toContain("/v1/oauth/register");
  expect(html).toContain("/.well-known/oauth-authorization-server");
  expect(html).toContain("resource_metadata");
  expect(html).toContain("get_call");
  for (const [, code] of ERRORS) expect(html).toContain(code);
  // Every example sends the key from the environment, never a real one.
  expect(html).not.toMatch(/Bearer sxk_(live|test)_[A-Za-z0-9]{6,}/);
  // Generic for every organisation: no customer or partner product names.
  expect(html).not.toMatch(/wise\s*life|pulse|dipak/i);
});

it("shows each request in curl and JavaScript, with a Copy button", async () => {
  const writeText = vi.fn(async () => undefined);
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<DevelopersPage />));
  const endpoint = host.querySelector("#api-add-lead")!;
  const tab = [...endpoint.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  expect(tab.map((item) => item.textContent)).toEqual(["curl", "JavaScript"]);
  expect(
    endpoint.querySelector('[role="tabpanel"] code')?.textContent,
  ).toContain("curl ");
  await act(async () => tab[1].click());
  const code = endpoint.querySelector('[role="tabpanel"] code')!.textContent!;
  expect(code).toContain('method: "POST"');
  expect(tab[1].getAttribute("aria-selected")).toBe("true");
  await act(async () =>
    endpoint
      .querySelector<HTMLButtonElement>(
        '[aria-label="Copy: POST /leads, JavaScript"]',
      )!
      .click(),
  );
  expect(writeText).toHaveBeenCalledWith(code);
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
