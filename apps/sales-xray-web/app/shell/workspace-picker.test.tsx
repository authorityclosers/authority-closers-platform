// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  WorkspacePicker,
  workspaceInitials,
  workspaceTint,
} from "./workspace-picker";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const photo = "/v1/me/sales-xray-profile/photo";
const logo = (n: number) =>
  `/v1/me/sales-xray-workspaces/${id(n)}/logo/${id(n + 10)}`;
const personal = {
  tenant_id: id(1),
  kind: "personal" as const,
  name: "Personal",
};
const org = (n: number, name: string) => ({
  tenant_id: id(n),
  kind: "organisation" as const,
  name,
  logo_url: logo(n),
});
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
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
const row = (name: string) =>
  Array.from(host.querySelectorAll("button")).find((button) =>
    button.textContent?.includes(name),
  )!;

it("shows each organisation's own logo, the profile photo and the current tick", async () => {
  const select = vi.fn();
  await act(async () =>
    root.render(
      <WorkspacePicker
        workspaces={[personal, org(2, "Cedar Studio"), org(3, "Maple Works")]}
        currentId={id(2)}
        personName="Mira Example"
        personPhotoUrl={photo}
        onSelect={select}
      />,
    ),
  );
  for (const [name, src] of [
    ["Cedar Studio", logo(2)],
    ["Maple Works", logo(3)],
    ["Personal", photo],
  ]) {
    const button = row(name);
    expect(button.querySelector("img")?.getAttribute("src")).toBe(src);
  }
  const current = row("Cedar Studio");
  expect(current.getAttribute("aria-current")).toBe("true");
  expect(current.querySelector('[aria-label="Current"]')).toBeTruthy();
  await act(async () => row("Maple Works").click());
  expect(select).toHaveBeenCalledWith(id(3));
});

it("keeps readable monograms when logos fail, with stable name-based tints", async () => {
  await act(async () =>
    root.render(
      <WorkspacePicker
        workspaces={[
          personal,
          org(2, "Cedar Studio"),
          { ...org(3, "Maple Works"), logo_url: null },
        ]}
        currentId={id(2)}
        personName="Mira Example"
        onSelect={() => {}}
      />,
    ),
  );
  const current = row("Cedar Studio");
  await act(async () => {
    current.querySelector("img")!.dispatchEvent(new Event("error"));
  });
  expect(current.textContent).toContain("CS");
  expect(row("Maple Works").querySelector("[data-kind]")?.textContent).toBe(
    "MW",
  );
  expect(row("Maple Works").querySelector("img")).toBeNull();
  expect(row("Personal").textContent).toContain("ME");
  expect(workspaceInitials("  cedar studio extra ")).toBe("CS");
  expect(workspaceInitials("Oak")).toBe("OA");
  expect(workspaceTint("Cedar Studio")).toBe(workspaceTint(" cedar studio "));
  expect(
    new Set(
      ["Cedar Studio", "Maple Works", "Silver Field", "Oak"].map(workspaceTint),
    ).size,
  ).toBeGreaterThan(1);
});

it("uses the header email initials when there is no profile name", async () => {
  await act(async () =>
    root.render(
      <WorkspacePicker
        workspaces={[personal]}
        currentId={id(1)}
        personEmail="mira@example.test"
        onSelect={() => {}}
      />,
    ),
  );
  expect(row("Personal").textContent).toContain("MI");
});

it("uses the same initials as the header if the private profile photo fails", async () => {
  await act(async () =>
    root.render(
      <WorkspacePicker
        workspaces={[personal]}
        currentId={id(1)}
        personName="Mira Example"
        personPhotoUrl={photo}
        onSelect={() => {}}
      />,
    ),
  );
  await act(async () => {
    row("Personal").querySelector("img")!.dispatchEvent(new Event("error"));
  });
  expect(row("Personal").querySelector("[data-kind]")?.textContent).toBe("ME");
});
