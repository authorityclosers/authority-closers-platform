import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProspectLinkControl } from "./prospect-link-control";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("next/link", () => ({
  default: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} />
  ),
}));
const call = "11111111-1111-4111-8111-111111111111";
const prospect = "22222222-2222-4222-8222-222222222222";
const membership = "33333333-3333-4333-8333-333333333333";
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: { personId: prospect, sessionId: membership, tenantId: call },
  retry: vi.fn(),
};
const reference = {
  submission_id: call,
  evidence: [
    {
      quote: "I run Fictional Studio.",
      segment_id: "s1",
      start_ms: 0,
      end_ms: 900,
    },
  ],
};
const page = {
  schema: "ac.sales-xray.prospect-link/1",
  submission_id: call,
  membership: null,
  next_offset: null,
  suggestions: [
    {
      prospect_id: prospect,
      name: "Mehta Example",
      previous_call_at: "2026-09-28T00:00:00Z",
      confirmed: false,
      details: [
        {
          key: "company",
          text: "Fictional Studio",
          current: reference,
          previous: reference,
        },
      ],
    },
  ],
};
let host: HTMLDivElement;
let root: Root;
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetcher = vi.fn();
  respond(page);
  vi.stubGlobal("fetch", fetcher);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
function respond(value: unknown, status = 200) {
  fetcher.mockImplementation(
    async () => new Response(JSON.stringify(value), { status }),
  );
}

async function render(value: WorkspaceAccessValue = access) {
  await act(async () =>
    root.render(
      <StrictMode>
        <WorkspaceAccessContext.Provider value={value}>
          <ProspectLinkControl submissionId={call} />
        </WorkspaceAccessContext.Provider>
      </StrictMode>,
    ),
  );
}
async function click(text: string) {
  const button = Array.from(host.querySelectorAll("button")).find(
    (b) => b.textContent === text,
  );
  expect(button).toBeDefined();
  await act(async () => button?.click());
}

it("shows both source quotes and writes only on explicit confirmation, including StrictMode", async () => {
  await render();
  expect(host.textContent).toContain("Mehta Example");
  expect(host.querySelector("details")?.textContent).toContain(
    "I run Fictional Studio.",
  );
  expect(
    fetcher.mock.calls.every(([, options]) => options.method === "GET"),
  ).toBe(true);
  respond({
    ...page,
    membership: { membership_id: membership, prospect_id: prospect },
  });
  await click("Confirm Mehta Example");
  const [url, options] = fetcher.mock.calls.at(-1)!;
  expect(url).toContain(`/calls/${call}/confirm`);
  expect(JSON.parse(options.body)).toEqual({
    prospect_id: prospect,
    expected_membership_id: null,
  });
  expect(options.signal.aborted).toBe(false);
  expect(host.querySelector(`a[href="/prospects/${prospect}"]`)).not.toBeNull();
});

it("does not fetch without confirmed session/workspace access", async () => {
  await render({ ...access, authenticated: false, context: null });
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.textContent).toBe("");
});

it("clears old suggestions on a workspace change and ignores the old pending request", async () => {
  await render();
  let finish: (response: Response) => void = () => {};
  fetcher.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  await render({
    ...access,
    context: { ...access.context!, tenantId: prospect },
  });
  expect(host.textContent).not.toContain("Mehta Example");
  await render({ ...access, authenticated: false, context: null });
  await act(async () => finish(new Response(JSON.stringify(page))));
  expect(host.textContent).toBe("");
});

it("keeps a stale-link conflict visible and disables confirmation until reload", async () => {
  await render();
  respond({}, 409);
  await click("Confirm Mehta Example");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "call link changed",
  );
  expect(
    Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent === "Confirm Mehta Example",
    )?.disabled,
  ).toBe(true);
});

it("rejects a suggestion that claims an already confirmed identity", async () => {
  respond({
    ...page,
    suggestions: [{ ...page.suggestions[0], confirmed: true }],
  });
  await render();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be verified",
  );
  expect(host.textContent).not.toContain("Confirm Mehta Example");
});

it("creates the first prospect through the same authenticated app path", async () => {
  respond({ ...page, suggestions: [] });
  await render();
  const input = host.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Fictional Mehta");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  respond({
    ...page,
    membership: { membership_id: membership, prospect_id: prospect },
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(fetcher.mock.calls.at(-1)![0]).toContain(`/calls/${call}/create`);
  expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body)).toEqual({
    display_name: "Fictional Mehta",
  });
});
