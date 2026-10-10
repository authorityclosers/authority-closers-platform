import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBrandingForTests } from "../shell/branding-store";
import { WorkspaceAccessProvider } from "../workspace-access";
import { CompanyLogoPanel } from "./company-logo-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const tenant = "11111111-1111-4111-8111-111111111111";
const logo = "/v1/organisation/logo/44444444-4444-4444-8444-444444444444";
const settings = {
  tenant_id: tenant,
  name: "Fictional Studio",
  legal_name: "",
  gstin: "",
  address: "",
  industry: "",
  team_size: "",
  website: "",
  city: "",
};
let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
let upload: (init: RequestInit) => Response;

beforeEach(() => {
  resetBrandingForTests();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  upload = () => Response.json({ ...settings, logo_url: logo });
  fetchMock = vi.fn(async (path: string, init?: RequestInit) =>
    path === "/v1/organisation/logo" && init?.method === "PUT"
      ? upload(init)
      : Response.json({
          tenant_id: tenant,
          name: "Fictional Studio",
          logo_url: null,
        }),
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn(),
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function render(canEdit = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p-1", sessionId: "s-1", tenantId: tenant },
          retry: () => {},
        }}
      >
        <CompanyLogoPanel name="Fictional Studio" canEdit={canEdit} />
      </WorkspaceAccessProvider>,
    ),
  );
}

const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (node) => node.textContent === label,
  );

async function choose(file: File) {
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
}

const png = (bytes = 10) =>
  new File([new Uint8Array(bytes)], "logo.png", { type: "image/png" });

it("lets an owner preview the square, save it and see it at once", async () => {
  await render();
  expect(host.querySelector("[aria-hidden]")?.textContent).toBe("FS");
  expect(button("Upload logo")).toBeDefined();
  await choose(png());
  const preview = host.querySelector<HTMLImageElement>(
    'img[alt="Preview of the new logo"]',
  );
  expect(preview?.getAttribute("src")).toBe("blob:preview");
  expect(button("Upload logo")).toBeUndefined();
  await act(async () => button("Save logo")!.click());
  const put = fetchMock.mock.calls.find(
    ([path]) => path === "/v1/organisation/logo",
  )!;
  const headers = new Headers((put[1] as RequestInit).headers);
  expect(headers.get("Content-Type")).toBe("image/png");
  expect(headers.get("Idempotency-Key")).toMatch(/^[\da-f-]{36}$/);
  expect(host.textContent).toContain("Logo saved.");
  expect(host.querySelector("img")?.getAttribute("src")).toBe(logo);
  expect(button("Replace logo")).toBeDefined();
});

it("refuses files the server would refuse, before uploading", async () => {
  await render();
  await choose(new File(["gif"], "logo.gif", { type: "image/gif" }));
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Choose a PNG, JPG or WebP image.",
  );
  await choose(png(2 * 1024 * 1024 + 1));
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Choose an image up to 2 MB.",
  );
  expect(
    fetchMock.mock.calls.some(([path]) => path === "/v1/organisation/logo"),
  ).toBe(false);
});

it("says plainly when the server refuses, and keeps the preview to retry", async () => {
  upload = () => Response.json({ detail: "bad" }, { status: 400 });
  await render();
  await choose(png());
  await act(async () => button("Save logo")!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Use a still PNG, JPG or WebP image up to 2 MB.",
  );
  expect(button("Save logo")).toBeDefined();
  await act(async () => button("Cancel")!.click());
  expect(host.querySelector('img[alt="Preview of the new logo"]')).toBeNull();
  expect(button("Upload logo")).toBeDefined();
});

it("shows members the logo without any way to change it", async () => {
  await render(false);
  expect(host.querySelector("button")).toBeNull();
  expect(host.querySelector('input[type="file"]')).toBeNull();
  expect(host.textContent).toContain(
    "Only owners and admins can change the logo.",
  );
});
