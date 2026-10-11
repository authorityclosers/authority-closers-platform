// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { CreateOrganisationDialog } from "./create-organisation-dialog";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const tenant = "00000000-0000-4000-8000-000000000003";

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const input = () => host.querySelector("input")!;
async function type(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input(), value);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
}

it("creates once per name, keeps the same key on a retry, and says why it failed", async () => {
  const onCreated = vi.fn();
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      Response.json(
        { detail: "Verify your email before creating an organisation." },
        { status: 403 },
      ),
    )
    .mockResolvedValueOnce(
      Response.json(
        {
          tenant_id: tenant,
          handle: "brightline",
          name: "Brightline",
          your_role: "owner",
        },
        { status: 201 },
      ),
    );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(
      <CreateOrganisationDialog
        open
        onClose={() => {}}
        onCreated={onCreated}
      />,
    ),
  );
  expect(host.querySelector("dialog h2")?.textContent).toBe(
    "Create an organisation",
  );

  await type(" B ");
  await submit();
  expect(host.textContent).toContain("Use 2 to 80 characters.");
  expect(fetchMock).not.toHaveBeenCalled();

  await type("  Brightline   ");
  await submit();
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Verify your email before creating an organisation.",
  );
  await submit();
  expect(onCreated).toHaveBeenCalledWith(tenant);
  const [first, second] = fetchMock.mock.calls as unknown as [
    string,
    RequestInit,
  ][];
  expect(JSON.parse(String(first[1].body))).toEqual({ name: "Brightline" });
  expect(new Headers(second[1].headers).get("Idempotency-Key")).toBe(
    new Headers(first[1].headers).get("Idempotency-Key"),
  );
  // The page moves into the new workspace; the button stays busy until then.
  expect(
    [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Creating…"),
    )?.disabled,
  ).toBe(true);
});
