import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CompanyInformation } from "./prospect-company-information";
import { CompanyList } from "./prospects/company-list";
import { fictionalCompany } from "./prospect-company.fixture";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
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
});

it("shows four company facts, explicit person links and exact source without guessing missing fields", async () => {
  const company = fictionalCompany();
  await act(async () => root.render(<CompanyInformation company={company} />));
  expect(host.querySelectorAll("dt")).toHaveLength(4);
  expect(host.textContent).toContain("Person edit · locked");
  expect(host.textContent).toContain("CityUnknown");
  expect(host.textContent).toContain("Business sizeUnknown");
  expect(host.querySelector("blockquote")?.textContent).toBe(
    "Fictional व्यवसाय manufactures test parts.",
  );
  expect(
    host.querySelector(
      'a[href="/prospects/00000000-0000-0000-0000-000000000013"]',
    ),
  ).not.toBeNull();
  expect(host.querySelector("input, button")).toBeNull();
  expect(host.textContent).not.toMatch(/score|rank|budget|probability/i);
});
it("respects server capabilities even when a caller supplies edit callbacks", async () => {
  const save = vi.fn(),
    confirm = vi.fn();
  await act(async () =>
    root.render(
      <CompanyInformation
        company={{ ...fictionalCompany(), can_edit: false, can_confirm: false }}
        onSave={save}
        onConfirm={confirm}
      />,
    ),
  );
  expect(host.querySelector("button, input")).toBeNull();
  expect(save).not.toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
});
it("sends only the inline value and company field chosen by the person", async () => {
  const save = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <CompanyInformation company={fictionalCompany()} onSave={save} />,
    ),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label^="Business size:"]')!
      .click(),
  );
  const input = host.querySelector<HTMLInputElement>("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "approximately 20 people");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(save).toHaveBeenCalledExactlyOnceWith(
    "size",
    "approximately 20 people",
  );
  // A save callback cannot create a confirmed/locked revision without server readback.
  expect(host.textContent).toContain("Business sizeUnknown");
});
it("opens equal-named companies by separate opaque IDs", async () => {
  const company = fictionalCompany(),
    onOpen = vi.fn();
  const otherId = "00000000-0000-0000-0000-000000000014";
  await act(async () =>
    root.render(
      <CompanyList
        companies={[company, { ...company, company_id: otherId }]}
        onOpen={onOpen}
      />,
    ),
  );
  const buttons = host.querySelectorAll<HTMLButtonElement>("button");
  expect(buttons).toHaveLength(2);
  await act(async () => buttons[0].click());
  await act(async () => buttons[1].click());
  expect(onOpen.mock.calls).toEqual([[company.company_id], [otherId]]);
});
it("requires an explicit confirmation action and never auto-links a person", async () => {
  const confirm = vi.fn();
  const company = {
    ...fictionalCompany(),
    origin: "detected" as const,
    confirmed_at: null,
    can_confirm: true,
    people: [],
  };
  await act(async () =>
    root.render(<CompanyInformation company={company} onConfirm={confirm} />),
  );
  expect(host.textContent).toContain(
    "Detected company · awaiting confirmation",
  );
  expect(host.textContent).toContain("No visible confirmed person links.");
  expect(confirm).not.toHaveBeenCalled();
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(confirm).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("awaiting confirmation");
});

it("does not carry an inline draft into a different company", async () => {
  const save = vi.fn(async () => {});
  const company = fictionalCompany();
  await act(async () =>
    root.render(<CompanyInformation company={company} onSave={save} />),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label^="Business size:"]')!
      .click(),
  );
  const input = host.querySelector<HTMLInputElement>("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Previous company draft");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    root.render(
      <CompanyInformation
        company={{
          ...company,
          company_id: "00000000-0000-0000-0000-000000000014",
        }}
        onSave={save}
      />,
    ),
  );
  expect(host.querySelector("input")).toBeNull();
  expect(host.textContent).not.toContain("Previous company draft");
  expect(save).not.toHaveBeenCalled();
});
