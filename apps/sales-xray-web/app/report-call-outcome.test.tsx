import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CallOutcomeEditor } from "./report-call-outcome";

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
function button(label: string) {
  return [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent === label,
  )!;
}
async function type(label: string, text: string) {
  const field = [...host.querySelectorAll("label")]
    .find((node) => node.textContent === label)!
    .querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("keeps absent data unavailable and an explicitly absent record unrecorded", async () => {
  const save = vi.fn();
  await act(async () =>
    root.render(<CallOutcomeEditor scopeKey="call-a" canEdit onSave={save} />),
  );
  expect(host.textContent).toContain("Couldn't load");
  expect(host.querySelector("button")).toBeNull();
  await act(async () =>
    root.render(
      <CallOutcomeEditor scopeKey="call-a" value={null} onSave={save} />,
    ),
  );
  expect(host.textContent).toContain("Not set yet");
  expect(host.textContent).not.toContain("Decision Pending");
  expect(save).not.toHaveBeenCalled();
});
it("requires current edit capability and an audited save port", async () => {
  const save = vi.fn();
  await act(async () =>
    root.render(
      <CallOutcomeEditor scopeKey="call-a" value={null} onSave={save} />,
    ),
  );
  expect(host.querySelector("button")).toBeNull();
  await act(async () =>
    root.render(<CallOutcomeEditor scopeKey="call-a" value={null} canEdit />),
  );
  expect(host.querySelector("button")).toBeNull();
});
it("records Won on one tap, prevents duplicate dispatch and waits for server readback", async () => {
  let finish: () => void = () => {};
  const save = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  await act(async () => {
    button("Won").click();
    button("Won").click();
  });
  expect(save).toHaveBeenCalledExactlyOnceWith({
    outcome: "won",
    lost_reason: null,
    follow_up_on: null,
    deal_value: null,
  });
  expect(host.textContent).toContain("Saving…");
  await act(async () => finish());
  expect(host.textContent).toContain("Not set yet");
  expect(host.textContent).not.toContain("Saved");
});
it("does not record Lost until a person supplies a reason", async () => {
  const save = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Lost").click());
  expect(save).not.toHaveBeenCalled();
  await act(async () => button("Save").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Add why it was lost",
  );
  expect(save).not.toHaveBeenCalled();
  expect(button("Try again").disabled).toBe(false);
  await type("Why was it lost?", "Chose a different option.");
  await act(async () => button("Save").click());
  expect(save).toHaveBeenCalledExactlyOnceWith({
    outcome: "lost",
    lost_reason: "Chose a different option.",
    follow_up_on: null,
    deal_value: null,
  });
});
it("retains the exact human follow-up date and optional amount/currency", async () => {
  const save = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Follow-up Set").click());
  await act(async () => button("Save").click());
  expect(save).not.toHaveBeenCalled();
  await type("Follow-up date", "2026-10-12");
  await act(async () => button("Deal value").click());
  await type("Amount", "123.0000");
  await type("Currency", "INR");
  await act(async () => button("Save").click());
  expect(save).toHaveBeenCalledExactlyOnceWith({
    outcome: "follow_up",
    lost_reason: null,
    follow_up_on: "2026-10-12",
    deal_value: { amount: "123.0000", currency_code: "INR" },
  });
});
it("requires a fresh read before retrying an unconfirmed write", async () => {
  const save = vi
    .fn()
    .mockRejectedValueOnce(new Error("private response"))
    .mockResolvedValueOnce(undefined);
  const reload = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
        onReload={reload}
      />,
    ),
  );
  await act(async () => button("Decision Pending").click());
  expect(host.textContent).toContain("We couldn't confirm your save");
  expect(host.querySelector("strong + span")?.textContent).toBe(
    "Not confirmed",
  );
  expect(host.textContent).not.toContain("private response");
  expect(button("Decision Pending").disabled).toBe(true);
  await act(async () => button("Decision Pending").click());
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => button("Reload").click());
  expect(reload).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Not set yet");
  await act(async () => button("Decision Pending").click());
  expect(save).toHaveBeenCalledTimes(2);
});

it("keeps unconfirmed state and write controls disabled if the fresh read fails", async () => {
  const save = vi.fn(async () => {
    throw new Error("private save detail");
  });
  const reload = vi.fn(async () => {
    throw new Error("private read detail");
  });
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
        onReload={reload}
      />,
    ),
  );
  await act(async () => button("Won").click());
  await act(async () => button("Reload").click());
  expect(host.textContent).toContain("Still couldn't load the outcome");
  expect(host.textContent).not.toContain("private");
  expect(host.querySelector("strong + span")?.textContent).toBe(
    "Not confirmed",
  );
  expect(button("Lost").disabled).toBe(true);
  expect(save).toHaveBeenCalledTimes(1);
});

it("uses one explicit page reload when no scoped read port is supplied", async () => {
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => {});
  const save = vi.fn(async () => {
    throw new Error("lost acknowledgement");
  });
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Won").click());
  await act(async () => {
    button("Reload").click();
    button("Reload").click();
  });
  expect(reload).toHaveBeenCalledTimes(1);
  expect(save).toHaveBeenCalledTimes(1);
  expect(button("Lost").disabled).toBe(true);
});

it("reads back a completed write without replaying it or presenting stale previous facts", async () => {
  const save = vi.fn(async () => {
    throw new Error("lost acknowledgement");
  });
  let finish: () => void = () => {};
  const reload = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const render = (
    value: null | {
      outcome: "won" | "lost";
      lost_reason: string | null;
      follow_up_on: null;
      deal_value: null;
    },
  ) =>
    root.render(
      <CallOutcomeEditor
        scopeKey="call-a"
        value={value}
        canEdit
        onSave={save}
        onReload={reload}
      />,
    );
  await act(async () =>
    render({
      outcome: "lost",
      lost_reason: "Previous reason",
      follow_up_on: null,
      deal_value: null,
    }),
  );
  await act(async () => button("Won").click());
  expect(host.textContent).not.toContain("Previous reason");
  await act(async () => {
    button("Reload").click();
    button("Reload").click();
  });
  expect(reload).toHaveBeenCalledTimes(1);
  expect(button("Reload").disabled).toBe(true);
  expect(host.textContent).toContain("Checking…");
  await act(async () => {
    render({
      outcome: "won",
      lost_reason: null,
      follow_up_on: null,
      deal_value: null,
    });
    finish();
  });
  expect(host.querySelector("strong + span")?.textContent).toBe("Won");
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelector('[aria-busy="true"]')).toBeNull();
  expect(save).toHaveBeenCalledTimes(1);
});
it("discards the previous call or account's draft when its scope changes", async () => {
  const save = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="account-a:call-a"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Lost").click());
  await type("Why was it lost?", "Previous private draft");
  await act(async () =>
    root.render(
      <CallOutcomeEditor
        scopeKey="account-b:call-b"
        value={null}
        canEdit
        onSave={save}
      />,
    ),
  );
  expect(host.querySelector("input")).toBeNull();
  await act(async () => button("Lost").click());
  expect(host.querySelector<HTMLInputElement>("input")!.value).toBe("");
  expect(save).not.toHaveBeenCalled();
});
