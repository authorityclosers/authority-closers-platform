// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const seen = vi.hoisted(() => ({
  notices: [] as { title?: string }[],
  options: null as null | {
    onKeyMade: (key: string) => void;
    refresh: number;
    extras: { keys?: ReactNode };
  },
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../notice-center", () => ({
  notify: (notice: { title?: string }) => seen.notices.push(notice),
}));
vi.mock("../organisation/organisation-view", () => ({
  OrganisationView: (props: {
    integrationOptions: NonNullable<typeof seen.options>;
  }) => {
    seen.options = props.integrationOptions;
    return (
      <div data-testid="integrations">
        {props.integrationOptions.extras.keys}
      </div>
    );
  },
}));

import {
  AssistantSetup,
  assistantSnippet,
  remoteSnippet,
} from "./assistant-setup";
import { DevelopersSection } from "./developers";
import { TryApi } from "./try-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  seen.notices = [];
  seen.options = null;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
async function type(
  field: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  await act(async () => {
    const proto =
      field instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(field, value);
    field.dispatchEvent(
      new Event(field instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
}

it("sends a real request with a pasted key, never with cookies, and shows the answer", async () => {
  const fetcher = vi.fn(async () =>
    Response.json({
      organisation: { name: "Brightline Coaching" },
      key: { scopes: [] },
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  const used = vi.fn();
  await act(async () => root.render(<TryApi freshKey={null} onUsed={used} />));
  expect(button("Send request")?.disabled).toBe(true);
  await type(
    host.querySelector<HTMLInputElement>('input[type="password"]')!,
    "sxk_test_abc",
  );
  await act(async () => button("Send request")!.click());
  await flush();
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/api/me",
    expect.objectContaining({
      credentials: "omit",
      headers: expect.objectContaining({
        authorization: "Bearer sxk_test_abc",
      }),
    }),
  );
  const answer = host.querySelector('[role="status"]')!;
  expect(answer.textContent).toContain("200");
  expect(answer.querySelector("code")?.textContent).toContain(
    '"name": "Brightline Coaching"',
  );
  expect(used).toHaveBeenCalledOnce();
  // The curl line never carries the key itself.
  expect(host.textContent).toContain('-H "Authorization: Bearer $SX_API_KEY"');
  expect(host.textContent).not.toContain("Bearer sxk_test_abc");
});

it("uses the key just made, and asks for a call id where the request needs one", async () => {
  const fetcher = vi.fn(async () =>
    Response.json(
      { error: { code: "scope_missing", message: "No." } },
      { status: 403 },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(<TryApi freshKey="sxk_test_new" onUsed={() => undefined} />),
  );
  expect(host.textContent).toContain("Using the key you just made");
  await type(host.querySelector("select")!, "facts");
  expect(button("Send request")?.disabled).toBe(true);
  await type(
    host.querySelector<HTMLInputElement>(
      'input[placeholder="An id from GET /calls"]',
    )!,
    "c 1",
  );
  await act(async () => button("Send request")!.click());
  await flush();
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/api/calls/c%201/facts",
    expect.objectContaining({
      headers: expect.objectContaining({
        authorization: "Bearer sxk_test_new",
      }),
    }),
  );
  expect(host.querySelector('[role="status"]')?.textContent).toContain("403");
});

it("says so in a corner card when the request can't reach the API", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("offline");
    }),
  );
  await act(async () =>
    root.render(<TryApi freshKey="sxk_test_new" onUsed={() => undefined} />),
  );
  await act(async () => button("Send request")!.click());
  await flush();
  expect(seen.notices).toEqual([
    expect.objectContaining({ title: "The request didn’t reach the API" }),
  ]);
  expect(host.querySelector('[role="status"]')).toBeNull();
});

it("writes each assistant's setup, naming the API address only off production", () => {
  const production = JSON.parse(
    assistantSnippet(
      "claude-desktop",
      "https://salesxray.authorityclosers.com",
    ),
  );
  expect(production.mcpServers["sales-xray"]).toEqual({
    command: "python3",
    args: ["/path/to/sx.py", "mcp"],
    env: { SX_API_KEY: "paste-your-key-here" },
  });
  const dev = JSON.parse(
    assistantSnippet("vscode", "https://salesxray-dev.authorityclosers.com"),
  );
  expect(dev.servers["sales-xray"]).toMatchObject({
    type: "stdio",
    env: { SX_API_BASE: "https://salesxray-dev.authorityclosers.com/v1/api" },
  });
  expect(
    assistantSnippet("claude-code", "https://salesxray.authorityclosers.com"),
  ).toBe(
    [
      "claude mcp add sales-xray",
      "  --env SX_API_KEY=paste-your-key-here",
      "  -- python3 /path/to/sx.py mcp",
    ].join(" \\\n"),
  );
});

it("writes the remote server's setup for each assistant at this site's address", () => {
  const dev = "https://salesxray-dev.authorityclosers.com";
  expect(remoteSnippet("chatgpt", dev)).toBe(`${dev}/v1/mcp`);
  expect(remoteSnippet("claude-desktop", dev)).toBe(`${dev}/v1/mcp`);
  expect(remoteSnippet("claude-code", dev)).toBe(
    `claude mcp add --transport http sales-xray ${dev}/v1/mcp`,
  );
  expect(JSON.parse(remoteSnippet("cursor", dev))).toEqual({
    mcpServers: { "sales-xray": { url: `${dev}/v1/mcp` } },
  });
  expect(JSON.parse(remoteSnippet("vscode", dev))).toEqual({
    servers: { "sales-xray": { type: "http", url: `${dev}/v1/mcp` } },
  });
  // Drawn on the server first: production's address until the page knows its own.
  expect(remoteSnippet("claude-desktop", "")).toBe(
    "https://salesxray.authorityclosers.com/v1/mcp",
  );
});

it("walks through connecting an assistant, remote first, with the download folded away", async () => {
  const writeText = vi.fn(async () => undefined);
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
  await act(async () => root.render(<AssistantSetup />));
  expect(host.querySelectorAll('[data-steps="remote"] > li')).toHaveLength(3);
  // ChatGPT first: it takes only the address, so there is nothing to download.
  expect(
    host.querySelector('[aria-label="ChatGPT setup"] code')?.textContent,
  ).toMatch(/\/v1\/mcp$/);
  expect(host.querySelector("details")).toBeNull();
  await act(async () => button("Claude")!.click());
  expect(host.querySelectorAll('[data-steps="stdio"] > li')).toHaveLength(3);
  expect(host.querySelector("details")?.hasAttribute("open")).toBe(false);
  expect(
    host.querySelector('a[href="/developers/sx.py"]')?.hasAttribute("download"),
  ).toBe(true);
  await act(async () => button("Claude Code")!.click());
  const code = host.querySelector(
    '[aria-label="Claude Code setup"] code',
  )!.textContent!;
  expect(code).toContain("claude mcp add --transport http sales-xray");
  expect(code).toContain("/v1/mcp");
  expect(
    host.querySelector('[aria-label="Claude Code setup on your computer"] code')
      ?.textContent,
  ).toContain("-- python3 /path/to/sx.py mcp");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Copy: Claude Code setup"]',
      )!
      .click(),
  );
  await flush();
  expect(writeText).toHaveBeenCalledWith(code);
  expect(
    host.querySelector('[aria-label="Copy: Claude Code setup: copied"]'),
  ).not.toBeNull();
});

it("puts the docs first, and hands a new key to Try it without saving it", async () => {
  await act(async () => root.render(<DevelopersSection />));
  expect(host.querySelector('a[href="/developers"]')?.textContent).toBe(
    "Read the docs",
  );
  expect(
    host.querySelector('[data-testid="integrations"]')?.textContent,
  ).toContain("Try the API");
  // The AI assistant first, before keys and Try it.
  const words = host.textContent!;
  expect(words.indexOf("Connect your AI assistant")).toBeGreaterThan(-1);
  expect(words.indexOf("Connect your AI assistant")).toBeLessThan(
    words.indexOf("Try the API"),
  );
  expect(host.textContent).not.toContain("Using the key you just made");
  await act(async () => seen.options!.onKeyMade("sxk_test_fresh"));
  expect(host.textContent).toContain("Using the key you just made");
  expect(seen.options!.refresh).toBe(0);
});
