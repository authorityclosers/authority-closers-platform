import { act, type ComponentProps, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import { companyBinding, fictionalCompany } from "../prospect-company.fixture";
import { CompanyPage, type CompanyPageRead } from "./company-page";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const company = fictionalCompany();
const ready: CompanyPageRead = {
  kind: "detail",
  value: { status: "ready", binding: companyBinding, data: company },
};
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: companyBinding,
  retry: vi.fn(),
};
async function show(
  read = ready,
  current: WorkspaceAccessValue | null = access,
  extra: Partial<ComponentProps<typeof CompanyPage>> = {},
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={current}>
        <CompanyPage read={read} {...extra} />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
function button(text: string) {
  return [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === text,
  )!;
}

it("renders one server-loaded profile without starting another read", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await show();
  expect(host.querySelector("h2")?.textContent).toBe(company.name);
  expect(
    host.querySelector(
      'a[href="/prospects/00000000-0000-0000-0000-000000000013"]',
    ),
  ).not.toBeNull();
  expect(button("Confirm company")).toBeUndefined();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each(["personId", "tenantId", "sessionId"])(
  "hides old Company names, quotes and links on a %s change",
  async (key) => {
    await show();
    await show(ready, {
      ...access,
      context: { ...companyBinding, [key]: company.company_id },
    });
    expect(host.textContent).not.toContain(company.name);
    expect(host.textContent).not.toContain("Fictional person");
    expect(host.textContent).not.toContain("manufactures test parts");
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
  },
);

it.each(["selecting", "unavailable", "unauthenticated"] as const)(
  "hides private data during %s",
  async (status) => {
    await show(ready, { ...access, status });
    expect(host.textContent).not.toContain(company.name);
    expect(host.textContent).not.toContain("Fictional person");
  },
);

it("keeps unavailable distinct from an authorised empty list and retries explicitly", async () => {
  const retry = vi.fn();
  await show(
    {
      kind: "list",
      value: {
        status: "unavailable",
        message: "Companies are unavailable. Try again.",
      },
    },
    access,
    { onRetry: retry },
  );
  expect(host.textContent).not.toContain("No companies recorded yet.");
  await act(async () => button("Try again").click());
  expect(retry).toHaveBeenCalledOnce();
});

it("uses a skeleton while a scoped page refresh is pending", async () => {
  await show(ready, access, { pending: true });
  expect(host.textContent).not.toContain(company.name);
  expect(
    host
      .querySelector('[aria-label="Loading companies"]')
      ?.getAttribute("aria-busy"),
  ).toBe("true");
});

it("keeps the first paint a skeleton until account scope arrives", async () => {
  await show(ready, null);
  expect(host.textContent).not.toContain(company.name);
  expect(host.querySelector('[aria-label="Loading companies"]')).not.toBeNull();
});

it("opens only a company id from an authorised server-loaded list", async () => {
  const open = vi.fn();
  await show(
    {
      kind: "list",
      value: {
        status: "ready",
        binding: companyBinding,
        data: { companies: [company], total: 1, next_offset: null },
      },
    },
    access,
    { onOpen: open },
  );
  const row = host.querySelector<HTMLButtonElement>(
    'section[aria-label="Companies"] button',
  )!;
  await act(async () => row.click());
  expect(open).toHaveBeenCalledWith(company.company_id);
});

it("disables a list action until an actual route handler exists", async () => {
  await show({
    kind: "list",
    value: {
      status: "ready",
      binding: companyBinding,
      data: { companies: [company], total: 1, next_offset: null },
    },
  });
  expect(
    host.querySelector<HTMLButtonElement>(
      'section[aria-label="Companies"] button',
    )?.disabled,
  ).toBe(true);
});
