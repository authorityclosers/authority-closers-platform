import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessProvider } from "../workspace-access";
import {
  brandingKey,
  parseBranding,
  resetBrandingForTests,
  updateBranding,
  useBranding,
  type Branding,
} from "./branding-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const tenant = "22222222-2222-4222-8222-222222222222";
const logo = "/v1/organisation/logo/44444444-4444-4444-8444-444444444444";
const context = { personId: "p-1", sessionId: "s-1", tenantId: tenant };
let root: Root;
let host: HTMLDivElement;
let seen: Array<Branding | null>;

function Probe({ enabled = true }: { enabled?: boolean }) {
  seen.push(useBranding(enabled));
  return null;
}

async function render(enabled = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          context,
          retry: () => {},
        }}
      >
        <Probe enabled={enabled} />
      </WorkspaceAccessProvider>,
    ),
  );
}

beforeEach(() => {
  resetBrandingForTests();
  seen = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("reads only well-formed branding; anything else is no logo", () => {
  expect(
    parseBranding({ tenant_id: tenant, name: "AC", logo_url: logo }),
  ).toEqual({ tenantId: tenant, name: "AC", logoUrl: logo });
  expect(
    parseBranding({
      tenant_id: tenant,
      name: "AC",
      logo_url: "https://x.test/a.png",
    })?.logoUrl,
  ).toBeNull();
  expect(
    parseBranding({ tenant_id: "nope", name: "AC", logo_url: null }),
  ).toBeNull();
  expect(parseBranding(null)).toBeNull();
  expect(parseBranding([])).toBeNull();
});

it("reads the workspace's branding once and shares it", async () => {
  const fetchMock = vi.fn(async () =>
    Response.json({ tenant_id: tenant, name: "AC", logo_url: logo }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await render();
  await render();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0]).toEqual([
    "/v1/organisation/branding",
    expect.objectContaining({ credentials: "same-origin" }),
  ]);
  expect(seen.at(-1)?.logoUrl).toBe(logo);
});

it("keeps initials when the server has no branding route or fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail: "Not Found" }, { status: 404 })),
  );
  await render();
  expect(seen.at(-1)).toBeNull();
  resetBrandingForTests();
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await render();
  expect(seen.at(-1)).toBeNull();
});

it("skips the read for a personal workspace", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await render(false);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(seen.at(-1)).toBeNull();
});

it("updates every reader at once after a logo change", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ tenant_id: tenant, name: "AC", logo_url: null }),
    ),
  );
  await render();
  expect(seen.at(-1)?.logoUrl).toBeNull();
  await act(async () =>
    updateBranding(brandingKey(context)!, {
      tenantId: tenant,
      name: "AC",
      logoUrl: logo,
    }),
  );
  expect(seen.at(-1)?.logoUrl).toBe(logo);
});
