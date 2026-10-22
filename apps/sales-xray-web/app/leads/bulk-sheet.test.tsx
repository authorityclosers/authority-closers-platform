// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => [] as { title?: string; tone?: string }[]);
vi.mock("../notice-center", () => ({
  notify: (notice: { title?: string; tone?: string }) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { BulkSheet } from "./bulk-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let sent: { url: string; body: Record<string, unknown> | undefined }[];
let templatesAt: "some" | "none" = "some";
const SELLER = "00000000-0000-4000-8000-000000000002";

beforeEach(() => {
  notices.length = 0;
  sent = [];
  templatesAt = "some";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (url === "/v1/lead-desk/team")
        return Response.json({
          reps: [
            {
              person_id: SELLER,
              name: "swamini fictional",
              open_leads: 12,
              available: true,
            },
          ],
        });
      if (url === "/v1/lead-desk/journey")
        return Response.json({
          stages: [
            { key: "new", label: "New enquiry", kind: "new", archived: false },
            {
              key: "not_connected",
              label: "Couldn't reach",
              kind: "not_connected",
              archived: false,
            },
            {
              key: "counselled",
              label: "Counselled",
              kind: "follow_up",
              archived: false,
            },
          ],
        });
      if (url === "/v1/lead-desk/whatsapp/status")
        return Response.json(
          templatesAt === "none"
            ? { numbers: [], templates: [] }
            : {
                numbers: [{ id: "n-1" }],
                templates: [
                  {
                    name: "welcome_lead",
                    language: "en",
                    status: "APPROVED",
                    text: "Hi {{1}}, thanks for your enquiry.",
                    parts: 1,
                  },
                  {
                    name: "site_visit",
                    language: "en",
                    status: "PENDING",
                    text: "Your visit is booked.",
                    parts: 0,
                  },
                ],
              },
        );
      if (url === "/v1/lead-desk/leads/bulk-whatsapp/preview")
        return Response.json({
          ready: 2,
          skipped: [
            {
              reason: "no_yes",
              words: "haven't said yes to WhatsApp",
              count: 1,
            },
          ],
          sent: 0,
          failed: 0,
          text: "Hi {name}, thanks for your enquiry.",
          limit: 100,
        });
      if (url === "/v1/lead-desk/leads/bulk-whatsapp")
        return Response.json({
          ready: 2,
          skipped: [],
          sent: 2,
          failed: 0,
          text: "",
          limit: 100,
        });
      if (url === "/v1/lead-desk/leads/bulk")
        return Response.json({
          done: 2,
          skipped: 0,
          words: "2 leads moved to Counselled.",
        });
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
}
const press = (text: string) =>
  [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(text),
  )!;

it("gives the ticked leads to one person in one request", async () => {
  const done = vi.fn();
  await act(async () =>
    root.render(
      <BulkSheet
        open
        leadIds={["a", "b"]}
        pipeline={null}
        onClose={() => undefined}
        onDone={done}
      />,
    ),
  );
  await flush();
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("2 leads selected");
  // One pipeline: no pipeline move on offer.
  expect(dialog.textContent).not.toContain("Move to a pipeline");
  await act(async () => press("Give to a person").click());
  await flush();
  expect(dialog.textContent).toContain("Swamini Fictional");
  await act(async () => press("Swamini Fictional").click());
  await flush();
  const bulk = sent.find((item) => item.url === "/v1/lead-desk/leads/bulk");
  expect(bulk?.body).toMatchObject({
    action: "assign",
    person_id: SELLER,
    lead_ids: ["a", "b"],
  });
  expect(done).toHaveBeenCalled();
});

it("moves them to one of the stages, never to Couldn't reach", async () => {
  await act(async () =>
    root.render(
      <BulkSheet
        open
        leadIds={["a", "b"]}
        pipeline={null}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await flush();
  await act(async () => press("Move to a stage").click());
  await flush();
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Counselled");
  expect(dialog.textContent).not.toContain("Couldn't reach");
  await act(async () => press("Counselled").click());
  await flush();
  expect(
    sent.find((item) => item.url === "/v1/lead-desk/leads/bulk")?.body,
  ).toMatchObject({ action: "stage", step: "counselled" });
  expect(notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "2 leads moved to Counselled.",
    }),
  ]);
});

async function open() {
  await act(async () =>
    root.render(
      <BulkSheet
        open
        leadIds={["a", "b", "c"]}
        pipeline={null}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await flush();
  await act(async () => press("Send a WhatsApp template").click());
  await flush();
  return document.querySelector("dialog")!;
}

// Orchestrator, 22 Oct 2026: WhatsApp's rules for a template to many leads.
it("sends an approved template only after saying who gets it and who is skipped", async () => {
  const dialog = await open();
  expect(dialog.textContent).toContain("welcome lead");
  expect(dialog.textContent).not.toContain("site visit"); // not approved
  await act(async () => press("welcome lead").click());
  expect(dialog.querySelector("input")?.value).toBe("{name}");
  await act(async () => press("Check who gets it").click());
  await flush();
  expect(dialog.textContent).toContain(
    "Goes to 2 leads who said yes to WhatsApp.",
  );
  expect(dialog.textContent).toContain(
    "1 lead skipped: haven't said yes to WhatsApp.",
  );
  expect(
    sent.some((item) => item.url === "/v1/lead-desk/leads/bulk-whatsapp"),
  ).toBe(false);
  await act(async () => press("Send to 2 leads").click());
  await flush();
  const send = sent.find(
    (item) => item.url === "/v1/lead-desk/leads/bulk-whatsapp",
  );
  expect(send?.body).toMatchObject({
    leadIds: ["a", "b", "c"],
    template: "welcome_lead",
    language: "en",
    values: ["{name}"],
    confirm: 2,
  });
  expect(typeof send?.body?.commandId).toBe("string");
  expect(notices).toEqual([
    expect.objectContaining({ tone: "success", title: "Sent to 2 leads" }),
  ]);
});

it("says how to start when no template is approved", async () => {
  templatesAt = "none";
  const dialog = await open();
  expect(dialog.textContent).toContain("No approved WhatsApp templates yet.");
});
