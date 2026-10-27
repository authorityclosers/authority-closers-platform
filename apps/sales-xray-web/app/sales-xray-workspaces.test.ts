import { afterEach, expect, it, vi } from "vitest";
import {
  parseSalesXrayWorkspaces,
  readSalesXrayWorkspaces,
} from "./sales-xray-workspaces";

const workspace = {
  tenant_id: "personal-id",
  kind: "personal",
  name: "Personal",
  role: null,
  sales_xray_enabled: true,
};
const choices = { selected_tenant_id: null, workspaces: [workspace] };
afterEach(() => vi.unstubAllGlobals());

it("preserves the directory fields and accepts no selection", () => {
  expect(parseSalesXrayWorkspaces(choices)).toEqual(choices);
});

it.each([
  { ...choices, person_id: "unexpected" },
  { ...choices, workspaces: [{ ...workspace, extra: true }] },
  { ...choices, workspaces: [{ ...workspace, kind: "operations" }] },
  { ...choices, workspaces: [{ ...workspace, kind: "unknown" }] },
  { ...choices, workspaces: [{ ...workspace, role: "learner" }] },
  { ...choices, workspaces: [{ ...workspace, sales_xray_enabled: "true" }] },
  { ...choices, workspaces: [{ ...workspace, sales_xray_enabled: undefined }] },
  { ...choices, workspaces: [{ ...workspace, tenant_id: "" }] },
  { ...choices, workspaces: [workspace, workspace] },
  { ...choices, selected_tenant_id: "absent" },
  { workspaces: [] },
])("rejects malformed and expanded responses: %j", (value) => {
  expect(parseSalesXrayWorkspaces(value)).toBeNull();
});

it("reads only the Sales X-Ray directory with the existing session", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json(choices));
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  await expect(readSalesXrayWorkspaces(signal)).resolves.toEqual(choices);
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/me/sales-xray-workspaces",
    expect.objectContaining({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
    }),
  );
});

it.each([401, 403, 404, 503])(
  "does not fall back on HTTP %s",
  async (status) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({}, { status }));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      readSalesXrayWorkspaces(new AbortController().signal),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledOnce();
  },
);

it("accepts optional member-scoped logos and the older directory shape", () => {
  const tenant = "00000000-0000-4000-8000-000000000004";
  const org = {
    ...workspace,
    tenant_id: tenant,
    kind: "organisation",
    name: "Cedar Studio",
    role: "member",
  };
  const logo_url = `/v1/me/sales-xray-workspaces/${tenant}/logo/00000000-0000-4000-8000-000000000008`;
  const value = { ...choices, workspaces: [{ ...org, logo_url }] };
  expect(parseSalesXrayWorkspaces(value)).toEqual(value);
  expect(
    parseSalesXrayWorkspaces({ ...choices, workspaces: [org] }),
  ).not.toBeNull();
  for (const logo of [
    "https://example.test/logo.png",
    "/v1/me/sales-xray-workspaces/00000000-0000-4000-8000-000000000099/logo/00000000-0000-4000-8000-000000000008",
    42,
  ]) {
    expect(
      parseSalesXrayWorkspaces({
        ...choices,
        workspaces: [{ ...org, logo_url: logo }],
      }),
    ).toBeNull();
  }
});
