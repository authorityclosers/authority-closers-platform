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

  // Design system v2: the current workspace first, with your role in it.
  const choices = [...menu.querySelectorAll("[role=menuitemradio]")];
  expect(choices.map((choice) => choice.getAttribute("aria-checked"))).toEqual([
    "true",
    "false",
  ]);
  expect(choices[0].textContent).toContain("Organisation · Owner");
  expect(choices[1].textContent).toContain("Personal · Just you");
  await act(async () => (choices[0] as HTMLElement).click());
  expect(onSelect).not.toHaveBeenCalled();
  await act(async () => (choices[1] as HTMLElement).click());
  expect(onSelect).toHaveBeenCalledWith(personal.tenant_id);
});

it("shows the organisation's logo in its tile, and the icon without one", async () => {
  const logo = "/v1/organisation/logo/44444444-4444-4444-8444-444444444444";
  const render = (logoUrl: string | null) =>
    act(async () =>
      root.render(
        <WorkspaceSwitcher
          workspaces={[personal, team]}
          currentId={team.tenant_id}
          personName="Asha Menon"
          branding={{ tenantId: team.tenant_id, name: team.name, logoUrl }}
          pending={false}
          open
          setOpen={() => {}}
          containerRef={createRef()}
          onSelect={() => {}}
        />,
      ),
    );
  await render(logo);
  const trigger = host.querySelector("[aria-haspopup=menu]")!;
  expect(trigger.querySelector("img")?.getAttribute("src")).toBe(logo);
  const rows = [...host.querySelectorAll("[role=menuitemradio]")];
  // Only the selected organisation's row: other workspaces keep their tiles.
  expect(rows.map((row) => Boolean(row.querySelector("img")))).toEqual([
    true,
    false,
  ]);
  await render(null);
  expect(trigger.querySelector("img")).toBeNull();
  expect(trigger.querySelector("svg")).not.toBeNull();
});

const invitation = {
  inviteId: "55555555-5555-4555-8555-555555555555",
  tenantId: "66666666-6666-4666-8666-666666666666",
  organisationName: "Brightline Coaching",
  role: "member",
  invitedAt: "2026-10-10T09:00:00Z",
  expiresAt: "2026-10-17T09:00:00Z",
} as const;

it("offers each invitation as one Join, and Create only where the server can", async () => {
  const onJoin = vi.fn();
  const onCreate = vi.fn();
  const render = (joining: string | null) =>
    act(async () =>
      root.render(
        <WorkspaceSwitcher
          workspaces={[personal]}
          currentId={personal.tenant_id}
          personName="Asha Menon"
          pending={false}
          open
          setOpen={() => {}}
          containerRef={createRef()}
          onSelect={() => {}}
          invites={[invitation]}
          joining={joining}
          onJoin={onJoin}
          onCreate={onCreate}
        />,
      ),
    );
  await render(null);
  expect(
    host.querySelector("[aria-haspopup=menu]")?.getAttribute("aria-label"),
  ).toBe("Current workspace: Personal · 1 invitation waiting");
  // Personal shows your own initials, never "PE" for the word Personal.
  expect(host.querySelector("[aria-haspopup=menu]")?.textContent).toContain(
    "AM",
  );
  const menu = host.querySelector("[role=menu]") as HTMLElement;
  // With an invitation waiting, "not in an organisation" would be beside the point.
  expect(menu.textContent).not.toContain("You are not in an organisation yet");
  const join = menu.querySelector<HTMLButtonElement>(
    '[aria-label="Join Brightline Coaching as a member"]',
  )!;
  expect(join.textContent).toContain("Invited as member");
  await act(async () => join.click());
  expect(onJoin).toHaveBeenCalledWith(invitation);
  const create = [...menu.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Create an organisation"),
  )!;
  await act(async () => create.click());
  expect(onCreate).toHaveBeenCalledTimes(1);

  await render(invitation.inviteId);
  const busy = host.querySelector<HTMLButtonElement>(
    '[aria-label="Join Brightline Coaching as a member"]',
  )!;
  expect(busy.disabled).toBe(true);
  expect(busy.textContent).toContain("Joining…");
});
