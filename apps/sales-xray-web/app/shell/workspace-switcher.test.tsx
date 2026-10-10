// @vitest-environment happy-dom
import { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "./workspace-switcher";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const personal = {
  tenant_id: "33333333-3333-4333-8333-333333333333",
  kind: "personal",
  name: "Personal",
  role: null,
  sales_xray_enabled: true,
} as const;
const team = {
  tenant_id: "22222222-2222-4222-8222-222222222222",
  kind: "organisation",
  name: "Authority Closers",
  role: "owner",
  sales_xray_enabled: true,
} as const;

it("names where you are and offers only what works: no Soon items", async () => {
  const onSelect = vi.fn();
  await act(async () =>
    root.render(
      <WorkspaceSwitcher
        workspaces={[personal, team]}
        currentId={team.tenant_id}
        personName="Asha Menon"
        pending={false}
        open
        setOpen={() => {}}
        containerRef={createRef()}
        onSelect={onSelect}
      />,
    ),
  );
  expect(
    host.querySelector("[aria-haspopup=menu]")?.getAttribute("aria-label"),
  ).toBe("Current workspace: Authority Closers");
  const menu = host.querySelector("[role=menu]") as HTMLElement;
  expect(menu.textContent).not.toContain("Soon");
  expect(menu.textContent).not.toContain("Create an organisation");
  expect(menu.textContent).not.toContain("Join with an invite");
  expect(menu.querySelectorAll("button:disabled")).toHaveLength(0);

  const choices = [...menu.querySelectorAll("[role=menuitemradio]")];
  expect(choices.map((choice) => choice.getAttribute("aria-checked"))).toEqual([
    "false",
    "true",
  ]);
  await act(async () => (choices[0] as HTMLElement).click());
  expect(onSelect).toHaveBeenCalledWith(personal.tenant_id);
});
