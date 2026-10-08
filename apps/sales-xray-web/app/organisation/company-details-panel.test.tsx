// @vitest-environment happy-dom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CompanyDetailsPanel } from "./company-details-panel";
import {
  organisationDetailFields,
  type OrganisationSettings,
} from "./organisation-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const tenant = "11111111-1111-4111-8111-111111111111";
const other = "22222222-2222-4222-8222-222222222222";
let root: Root;
let host: HTMLDivElement;
let server: OrganisationSettings;
let props: ComponentProps<typeof CompanyDetailsPanel>;
let fetchMock: ReturnType<typeof vi.fn>;
let mounted: boolean;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mounted = true;
  server = {
    tenant_id: tenant,
    name: "Fictional Studio",
    legal_name: "Fictional Limited",
    gstin: "FICTIONAL",
    address: "123 Example Street",
    industry: "Training",
    team_size: "3-10",
    website: "https://example.test",
    city: "Example City",
    logo_url: null,
  };
  props = {
    tenantId: tenant,
    role: "owner",
    authenticated: true,
    refresh: vi.fn(),
    onAccessLost: vi.fn(),
    onPersonal: vi.fn(),
  };
  fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as Record<string, string>;
      server = {
        ...server,
        ...Object.fromEntries(
          Object.entries(body).map(([key, value]) => [key, value.trim()]),
        ),
      };
    }
    return json(server);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  if (mounted) await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function render(change: Partial<typeof props> = {}) {
  props = { ...props, ...change };
  await act(async () => root.render(<CompanyDetailsPanel {...props} />));
}
const input = (key: string) =>
  host.querySelector<HTMLInputElement>(`input[name="${key}"]`)!;
async function edit(key: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input(key), value);
    input(key).dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function submit() {
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}
const save = () => act(async () => submit());
const writes = () =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT") as [
    string,
    RequestInit,
  ][];
const requestKey = (index: number) =>
  new Headers(writes()[index][1].headers).get("Idempotency-Key");

it.each(["owner", "admin"] as const)(
  "loads and saves all details as %s, adopts server normalization and reads persisted values on entry",
  async (role) => {
    await render({ role });
    expect(host.querySelectorAll("input")).toHaveLength(8);
    for (const key of organisationDetailFields)
      expect(input(key).value).toBe(server[key]);
    for (const key of organisationDetailFields)
      await edit(
        key,
        key === "name" ? "  New Fictional Studio  " : `Updated ${key}`,
      );
    await save();
    expect(writes()).toHaveLength(1);
    expect(Object.keys(JSON.parse(String(writes()[0][1].body))).sort()).toEqual(
      [...organisationDetailFields].sort(),
    );
    expect(input("name").value).toBe("New Fictional Studio");
    expect(host.textContent).toContain("Saved.");
    expect(props.refresh).toHaveBeenCalledOnce();
    await act(async () => root.render(null));
    await render();
    expect(
      fetchMock.mock.calls.filter(([, init]) => !init?.method),
    ).toHaveLength(2);
    for (const key of organisationDetailFields)
      expect(input(key).value).toBe(server[key]);
    expect(host.textContent).not.toContain("Saved.");
  },
);

it("clears optional fields without dropping unchanged loaded values and uses the exact field limits", async () => {
  await render();
  const limits = [80, 200, 32, 1000, 100, 80, 500, 100];
  organisationDetailFields.forEach((key, index) => {
    expect(input(key).maxLength).toBe(limits[index]);
    expect(input(key).type).toBe("text");
    expect(input(key).required).toBe(key === "name");
    expect(input(key).closest("label")?.textContent).toBeTruthy();
  });
  await edit("city", "");
  await save();
  const body = JSON.parse(String(writes()[0][1].body));
  expect(body.city).toBe("");
  expect(body.team_size).toBe("3-10");
  expect(body.legal_name).toBe("Fictional Limited");
});
it.each([" ", " a ", "a".repeat(81)])(
  "rejects an invalid trimmed name without writing",
  async (name) => {
    await render();
    await edit("name", name);
    await save();
    expect(writes()).toHaveLength(0);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("2–80");
  },
);
it("disables duplicate submission while preserving visible pending state", async () => {
  await render();
  const pending = deferred();
  fetchMock.mockImplementationOnce(() => pending.promise);
  await act(async () => {
    submit();
    submit();
  });
  expect(writes()).toHaveLength(1);
  expect(
    host.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled,
  ).toBe(true);
  expect(host.textContent).toContain("Saving…");
  expect(
    [...host.querySelectorAll<HTMLInputElement>("input")].every(
      (field) => field.disabled,
    ),
  ).toBe(true);
  await act(async () => pending.resolve(json(server)));
});

it.each([404, 409, 422, 500, "network"])(
  "keeps the draft and saved state on %s failure",
  async (status) => {
    await render();
    await edit("name", "Unsaved Fictional Studio");
    if (status === "network")
      fetchMock.mockRejectedValueOnce(new TypeError("Offline"));
    else
      fetchMock.mockResolvedValueOnce(
        json({ detail: "Fictional failure" }, Number(status)),
      );
    await save();
    expect(input("name").value).toBe("Unsaved Fictional Studio");
    expect(server.name).toBe("Fictional Studio");
    expect(props.refresh).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain("Saved.");
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(host.textContent).toContain(
      status === 422 ? "Check the company details" : "not saved",
    );
  },
);
it("offers an explicit same-key 409 retry, then gives an edited intent a new UUIDv4", async () => {
  await render();
  await edit("name", "Fictional Second Studio");
  fetchMock.mockResolvedValueOnce(json({ detail: "Busy" }, 409));
  await save();
  expect(host.textContent).toContain("Retry save");
  expect(writes()).toHaveLength(1);
  fetchMock.mockResolvedValueOnce(json({ detail: "Busy" }, 409));
  await save();
  expect(requestKey(0)).toBe(requestKey(1));
  await edit("city", "New Example City");
  await save();
  expect(requestKey(2)).not.toBe(requestKey(1));
  expect(requestKey(2)).toMatch(
    /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/,
  );
});
it.each([401, 403])(
  "clears private details and refreshes access once on HTTP %i",
  async (status) => {
    await render();
    await edit("name", "Private Fictional Draft");
    fetchMock.mockResolvedValueOnce(json({ detail: "Access changed" }, status));
    await save();
    expect(host.querySelector("input")).toBeNull();
    expect(host.textContent).not.toContain("Private Fictional Draft");
    expect(props.onAccessLost).toHaveBeenCalledOnce();
    expect(props.refresh).not.toHaveBeenCalled();
    await render();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  },
);
it.each([401, 403])(
  "does not expose an editor when the initial read returns HTTP %i",
  async (status) => {
    fetchMock.mockResolvedValueOnce(json({ detail: "Access changed" }, status));
    await render();
    expect(host.querySelector("form")).toBeNull();
    expect(props.onAccessLost).toHaveBeenCalledOnce();
  },
);
it.each([404, 500, "network"])(
  "offers a real read retry for %s without fixture details",
  async (status) => {
    if (status === "network")
      fetchMock.mockRejectedValueOnce(new TypeError("Offline"));
    else
      fetchMock.mockResolvedValueOnce(
        json({ detail: "Not Found" }, Number(status)),
      );
    await render();
    expect(host.querySelector("input")).toBeNull();
    expect(host.textContent).toContain("could not be loaded");
    expect(host.textContent).not.toContain("Coming soon");
    expect(props.onPersonal).not.toHaveBeenCalled();
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(input("name").value).toBe("Fictional Studio");
  },
);
it.each(["read", "write"])(
  "uses the exact Personal fallback on a %s 404",
  async (operation) => {
    if (operation === "write") await render();
    fetchMock.mockResolvedValueOnce(
      json({ detail: "No organisation selected." }, 404),
    );
    if (operation === "write") await save();
    else await render();
    expect(props.onPersonal).toHaveBeenCalledOnce();
    expect(props.onAccessLost).not.toHaveBeenCalled();
  },
);
it.each([
  { role: "member" as const },
  { authenticated: false },
  { tenantId: null },
])("makes no private request or draft for %j", async (change) => {
  await render(change);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(host.querySelector("form")).toBeNull();
});

it.each(["tenant", "role", "sign-out", "unmount"])(
  "ignores a delayed read after %s",
  async (change) => {
    const old = { ...server };
    const pending = deferred();
    fetchMock.mockImplementationOnce(() => pending.promise);
    await render();
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    if (change === "tenant") {
      server = { ...server, tenant_id: other, name: "Other Fictional Studio" };
      await render({ tenantId: other });
    }
    if (change === "role") await render({ role: "member" });
    if (change === "sign-out") await render({ authenticated: false });
    if (change === "unmount") {
      await act(async () => root.unmount());
      mounted = false;
    }
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(json(old)));
    expect(host.textContent).not.toContain("Fictional Limited");
    expect(
      host.querySelector<HTMLInputElement>('input[name="name"]')?.value,
    ).toBe(change === "tenant" ? "Other Fictional Studio" : undefined);
  },
);
it.each(["tenant", "role", "sign-out", "unmount"])(
  "ignores a delayed write and header refresh after %s",
  async (change) => {
    await render();
    const old = { ...server, name: "Old Saved Fictional Studio" };
    const pending = deferred();
    fetchMock.mockImplementationOnce(() => pending.promise);
    await save();
    const signal = writes()[0][1].signal as AbortSignal;
    if (change === "tenant") {
      server = { ...server, tenant_id: other, name: "Other Fictional Studio" };
      await render({ tenantId: other });
    }
    if (change === "role") await render({ role: "member" });
    if (change === "sign-out") await render({ authenticated: false });
    if (change === "unmount") {
      await act(async () => root.unmount());
      mounted = false;
    }
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(json(old)));
    expect(props.refresh).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain("Saved.");
    expect(
      host.querySelector<HTMLInputElement>('input[name="name"]')?.value,
    ).toBe(change === "tenant" ? "Other Fictional Studio" : undefined);
  },
);
it("rejects a different returned tenant without a successful save or header refresh", async () => {
  await render();
  await edit("name", "Unsaved Fictional Draft");
  fetchMock.mockResolvedValueOnce(
    json({ ...server, tenant_id: other, name: "Wrong Studio" }),
  );
  await save();
  expect(input("name").value).toBe("Unsaved Fictional Draft");
  expect(props.refresh).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain("Saved.");
});
it("clears a denied scope when switching tenant or losing and regaining management rights", async () => {
  fetchMock.mockResolvedValueOnce(json({ detail: "Forbidden" }, 403));
  await render();
  await render({ role: "member" });
  await render({ role: "admin" });
  expect(input("name").value).toBe(server.name);
  server = { ...server, tenant_id: other, name: "Other Fictional Studio" };
  await render({ tenantId: other });
  expect(input("name").value).toBe(server.name);
});
