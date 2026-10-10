import { act, StrictMode, type ComponentProps } from "react";
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
const transcript = {
  source_sha256: "a".repeat(64),
  revision: "fictional-r1",
  timebase_id: "1ms",
  duration_ms: 1000,
  segments: [
    {
      id: "s-name",
      speaker_id: "buyer",
      text: "I’m Fictional Mehta.",
      start_ms: 0,
      end_ms: 900,
    },
  ],
};
const speakerMap = {
  schema: "ac.sales-xray.speaker-map/1",
  submission_id: call,
  transcript_revision: transcript.revision,
  status: "predicted",
  speakers: [
    {
      speaker_id: "buyer",
      role: "prospect",
      display_name: "Fictional Mehta",
      name_source: "stated_in_call",
      name_evidence: [{ segment_id: "s-name", start_ms: 0, end_ms: 900 }],
    },
  ],
};
let mapResponse: unknown;
let host: HTMLDivElement;
let root: Root;
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetcher = vi.fn();
  mapResponse = speakerMap;
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
    async (url: string) =>
      new Response(
        JSON.stringify(url.endsWith("/speaker-map") ? mapResponse : value),
        { status },
      ),
  );
}

async function render(
  value: WorkspaceAccessValue = access,
  props: Partial<ComponentProps<typeof ProspectLinkControl>> = {},
) {
  await act(async () =>
    root.render(
      <StrictMode>
        <WorkspaceAccessContext.Provider value={value}>
          <ProspectLinkControl submissionId={call} {...props} />
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
  await click("Same as Mehta Example?");
  const [url, options] = fetcher.mock.calls.at(-1)!;
  expect(url).toContain(`/calls/${call}/confirm`);
  expect(JSON.parse(options.body)).toEqual({
    prospect_id: prospect,
    expected_membership_id: null,
  });
  expect(options.signal.aborted).toBe(false);
  expect(options.redirect).toBe("error");
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
  await click("Same as Mehta Example?");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "call link changed",
  );
  expect(
    Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent === "Same as Mehta Example?",
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
  expect(host.textContent).not.toContain("Same as Mehta Example?");
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

it("prefills a stated name, plays its transcript quote and creates only on a tap", async () => {
  const play = vi.fn();
  respond({ ...page, suggestions: [] });
  await render(access, { transcript, onSelectEvidence: play });
  expect(host.querySelector("input")!.value).toBe("Fictional Mehta");
  expect(host.textContent).toContain("I’m Fictional Mehta.");
  expect(
    fetcher.mock.calls.every(
      ([, options]) => !options.method || options.method === "GET",
    ),
  ).toBe(true);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label^="Play source moment"]')!
      .click(),
  );
  expect(play).toHaveBeenCalledWith(
    {
      segment_id: "s-name",
      quote: "I’m Fictional Mehta.",
      start_ms: 0,
      end_ms: 900,
    },
    "Prospect name",
  );
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
  expect(host.querySelector(`a[href="/prospects/${prospect}"]`)).not.toBeNull();
});

it.each(["user", "account_profile", "model", null])(
  "leaves the name blank for %s rather than treating it as stated",
  async (name_source) => {
    mapResponse = {
      ...speakerMap,
      speakers: [{ ...speakerMap.speakers[0], name_source }],
    };
    await render(access, { transcript });
    expect(host.querySelector("input")!.value).toBe("");
    expect(
      host.querySelector('button[type="submit"]')!.hasAttribute("disabled"),
    ).toBe(true);
    expect(host.textContent).not.toContain("Name heard");
  },
);

it.each(["missing", "revision", "evidence", "ambiguous"])(
  "keeps manual entry available with a %s map",
  async (kind) => {
    mapResponse =
      kind === "missing"
        ? {}
        : kind === "revision"
          ? { ...speakerMap, transcript_revision: "old-r1" }
          : {
              ...speakerMap,
              speakers:
                kind === "ambiguous"
                  ? [...speakerMap.speakers, speakerMap.speakers[0]]
                  : [
                      {
                        ...speakerMap.speakers[0],
                        name_evidence: [
                          { segment_id: "unknown", start_ms: 0, end_ms: 900 },
                        ],
                      },
                    ],
            };
    await render(access, { transcript });
    expect(host.querySelector("input")!.value).toBe("");
    expect(host.querySelector("form")).not.toBeNull();
  },
);

it("keeps a person's edit when the speaker map arrives later", async () => {
  let finish: (response: Response) => void = () => {};
  fetcher.mockImplementation(async (url: string) =>
    url.endsWith("/speaker-map")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : new Response(JSON.stringify(page)),
  );
  await render(access, { transcript });
  const input = host.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Person’s correction");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => finish(new Response(JSON.stringify(speakerMap))));
  expect(input.value).toBe("Person’s correction");
  expect(host.textContent).toContain(
    "Name heard in this call: Fictional Mehta",
  );
});

it("creates the detected fallback once per load and confirms only after one explicit tap", async () => {
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith(`/${prospect}/confirm`)) {
      expect(JSON.parse(init!.body as string)).toEqual({
        expected_revision: 2,
      });
      return new Response(
        JSON.stringify({
          schema: "ac.sales-xray.prospect-confirmation/1",
          prospect_id: prospect,
          revision: 3,
          confirmed_at: "2026-10-10T08:00:00Z",
        }),
      );
    }
    return new Response(
      JSON.stringify({
        ...page,
        membership: { prospect_id: prospect, membership_id: membership },
        linked_prospect: {
          name: "Name not heard",
          origin: "detected",
          revision: 2,
          confirmed_at: null,
        },
        suggestions: [],
      }),
    );
  });
  await render(access, { autoDetect: true });
  expect(
    fetcher.mock.calls.some(
      ([url, init]) => url.endsWith("/detect") && init.method === "POST",
    ),
  ).toBe(true);
  expect(host.textContent).toContain("Detected prospect · not yet confirmed");
  expect(host.textContent).not.toContain("Confirmed link.");
  expect(
    fetcher.mock.calls.some(([url]) => url.endsWith(`/${prospect}/confirm`)),
  ).toBe(false);
  await click("Confirm prospect");
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith(`/${prospect}/confirm`)),
  ).toHaveLength(1);
});
