import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ProspectInformation, PROSPECT_SECTIONS } from "./prospect-information";
import * as client from "./prospects-client";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";
import * as notices from "./notice-center";

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

it("prioritizes six sections, keeps missing qualification unknown and the person value visible through a contradiction", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(<ProspectInformation prospect={syntheticProspect} />),
    );
    const sections = [...host.querySelectorAll("[data-prospect-section]")];
    expect(sections).toHaveLength(6);
    expect(
      sections.map((section, i) =>
        section.textContent!.includes(PROSPECT_SECTIONS[i][0]),
      ),
    ).toEqual(Array(6).fill(true));
    expect(
      host.querySelector('[data-prospect-section="2"]')?.hasAttribute("open"),
    ).toBe(false);
    const company = host.querySelector('[data-fact-label="Contradiction"]');
    expect(company?.querySelector("dd")?.textContent).toBe("Example company");
    expect(company?.textContent).toContain("Person edit · locked");
    expect(company?.textContent).toContain("Example company two.");
    expect(host.textContent).toContain("Ability to investUnknown");
    expect(host.textContent).toContain("Willingness to investUnknown");
    expect(
      host.querySelector(
        'a[href="/analysis/calls/33333333-3333-4333-8333-333333333333?section=transcript"]',
      ),
    ).not.toBeNull();
    expect(host.textContent).not.toMatch(/score|probability|readiness score/i);
    expect(host.textContent).not.toContain("Edit a field");
  } finally {
    await act(async () => root.unmount());
  }
});

it("saves only text typed by a person, then requests a fresh server read", async () => {
  const host = document.createElement("div"),
    root = createRoot(host),
    onSaved = vi.fn();
  const edit = vi.spyOn(client, "editProspectField").mockResolvedValue();
  try {
    await act(async () =>
      root.render(
        <ProspectInformation prospect={syntheticProspect} onSaved={onSaved} />,
      ),
    );
    await act(async () =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Edit a field")!
        .click(),
    );
    const input = host.querySelector<HTMLInputElement>("input")!;
    expect(input.value).toBe(""); // Never copy AI text into a human-confirmed edit.
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    await act(async () => {
      setter.call(input, "Typed name");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () =>
      host
        .querySelector<HTMLFormElement>("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    expect(edit).toHaveBeenCalledWith(
      syntheticProspect.prospect_id,
      3,
      "name",
      "Typed name",
    );
    expect(onSaved).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    edit.mockRestore();
  }
});

it("shows Changed only when the API supplies an earlier value and its source", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  const name = syntheticProspect.profile_fields!.name!;
  if (name.state !== "known" || !name.evidence)
    throw new Error("missing source");
  try {
    await act(async () =>
      root.render(
        <ProspectInformation
          prospect={{
            ...syntheticProspect,
            profile_fields: {
              name: {
                ...name,
                changed_from: {
                  value: { kind: "text", text: "Earlier fictional name" },
                  set_at: "2026-10-09T00:00:00Z",
                  evidence: {
                    ...name.evidence!,
                    quote: "Earlier fictional name",
                  },
                },
              },
            },
          }}
        />,
      ),
    );
    const changed = host.querySelector('[data-fact-label="Changed"]');
    expect(changed?.querySelector("dd")?.textContent).toBe("अदिती");
    expect(changed?.textContent).toContain("Previously recorded");
    expect(changed?.textContent).toContain("Earlier fictional name");
  } finally {
    await act(async () => root.unmount());
  }
});

it("keeps the current value on a failed save and refreshes before an explicit retry", async () => {
  const host = document.createElement("div"),
    root = createRoot(host),
    onSaved = vi.fn();
  const edit = vi
    .spyOn(client, "editProspectField")
    .mockRejectedValue(new Error("This prospect changed. Reload."));
  const notice = vi.spyOn(notices, "notify").mockImplementation(() => {});
  try {
    await act(async () =>
      root.render(
        <ProspectInformation prospect={syntheticProspect} onSaved={onSaved} />,
      ),
    );
    await act(async () =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Edit a field")!
        .click(),
    );
    const input = host.querySelector<HTMLInputElement>("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "Typed edit");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () =>
      host
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    expect(
      host.querySelector('[data-prospect-section="1"] dd')?.textContent,
    ).toBe("अदिती");
    expect(onSaved).not.toHaveBeenCalled();
    expect(notice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: "error",
        title: "Edit wasn't saved",
        action: { label: "Try again", run: expect.any(Function) },
      }),
    );
    await act(async () => notice.mock.calls[0][0].action!.run());
    expect(onSaved).toHaveBeenCalledOnce();
    expect(edit).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    edit.mockRestore();
    notice.mockRestore();
  }
});

it("confirms a detected prospect without turning heard values into person edits", async () => {
  const host = document.createElement("div"),
    root = createRoot(host),
    onSaved = vi.fn();
  const confirm = vi
    .spyOn(client, "confirmDetectedProspect")
    .mockResolvedValue();
  const edit = vi.spyOn(client, "editProspectField").mockResolvedValue();
  try {
    await act(async () =>
      root.render(
        <ProspectInformation prospect={syntheticProspect} onSaved={onSaved} />,
      ),
    );
    const button = Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent === "Confirm prospect",
    )!;
    expect(confirm).not.toHaveBeenCalled();
    await act(async () => button.click());
    expect(confirm).toHaveBeenCalledWith(syntheticProspect.prospect_id, 3);
    expect(edit).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledOnce();
    // Confirmation is shown only from the refreshed server payload.
    expect(host.textContent).toContain("not yet confirmed");
  } finally {
    await act(async () => root.unmount());
    confirm.mockRestore();
    edit.mockRestore();
  }
});

it("keeps shared customer pages read-only when the server withholds edit and confirmation permission", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <ProspectInformation
          prospect={{
            ...syntheticProspect,
            can_edit: false,
            can_confirm: false,
          }}
          onSaved={vi.fn()}
        />,
      ),
    );
    expect(host.textContent).not.toContain("Edit a field");
    expect(host.textContent).not.toContain("Confirm prospect");
    expect(host.querySelectorAll("[data-prospect-section]")).toHaveLength(6);
  } finally {
    await act(async () => root.unmount());
  }
});
