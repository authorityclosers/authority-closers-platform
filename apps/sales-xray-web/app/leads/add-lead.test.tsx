import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

const addLead = vi.fn();
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  addLead: (...args: unknown[]) => addLead(...args),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { AddLeadDialog } from "./capture-dialogs";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

async function mount(canManage = false) {
  const onAdded = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <AddLeadDialog
        open
        canManage={canManage}
        onClose={() => {}}
        onAdded={onAdded}
      />,
    ),
  );
  return { onAdded, dialog: host.querySelector("dialog")! };
}

const labels = (dialog: HTMLElement) =>
  Array.from(dialog.querySelectorAll("label > span:first-child"), (span) =>
    span.textContent?.trim(),
  );

function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  addLead.mockReset();
});

// Owner, 22 Oct: adding a lead must be low effort.
it("asks only for a name and a phone; the rest waits behind More details", async () => {
  const { dialog } = await mount();
  expect(labels(dialog)).toEqual(["Name", "Phone"]);
  const phone = dialog.querySelectorAll("input")[1];
  expect(phone.type).toBe("tel");
  const more = Array.from(dialog.querySelectorAll("button")).find(
    (button) => button.textContent?.trim() === "More details",
  )!;
  await act(async () => more.click());
  expect(labels(dialog)).toEqual(
    expect.arrayContaining(["Interested in", "City", "Email", "Note"]),
  );
});

it("adds the lead from the keyboard's Enter and hands its id back", async () => {
  addLead.mockResolvedValue({ lead: { lead_id: "lead-1" } });
  const { dialog, onAdded } = await mount();
  const [name, phone] = Array.from(dialog.querySelectorAll("input"));
  await act(async () => {
    type(name, "Asha Fictional");
    type(phone, "98765 43210");
  });
  await act(async () =>
    dialog
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(addLead).toHaveBeenCalledTimes(1);
  expect(addLead.mock.calls[0][0]).toMatchObject({
    name: "Asha Fictional",
    phone: "98765 43210",
    source: "manual",
    assign: "me",
  });
  expect(onAdded).toHaveBeenCalledWith("lead-1");
});

it("says what is missing instead of sending an empty lead", async () => {
  const { dialog } = await mount();
  await act(async () =>
    dialog
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(addLead).not.toHaveBeenCalled();
  expect(dialog.querySelector('[role="alert"]')?.textContent).toBe(
    "Add a name or a phone number.",
  );
});

it("lets owners and admins choose who gets it", async () => {
  const { dialog } = await mount(true);
  expect(dialog.querySelector('[aria-label="Who gets it"]')).not.toBeNull();
});
