import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { requestSalesXrayLogout } from "./account-navigation";
import { CallMap } from "./call-map";
import type { SalesReport, Transcript } from "./report-contract";
import { useSpeakerProfiles } from "./speaker-profiles";
import { SpeakerServerProfiles } from "./speaker-server-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const CALL = "4f0c2a77-1b53-4c55-8d11-9f3a2b6e7c10";
const transcript = fixture.transcript as Transcript;
const ids = [...new Set(transcript.segments.map((s) => s.speaker_id!))];
const key = `ac.xray.speakers.v1:${CALL}`;
let root: Root;
let host: HTMLDivElement;
let data: ReturnType<typeof initial>;
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
let rejectPut: number | undefined;
let pendingPut: Promise<Response> | undefined;
function initial() {
  return {
    schema: "ac.sales-xray.speaker-map/1",
    submission_id: CALL,
    transcript_revision: transcript.revision as string | null,
    unavailable_reason: null as string | null,
    map_revision: null as string | null,
    report_basis: null,
    user_revision: 1,
    status: "confirmed",
    speakers: ids.map((speaker_id, index) => ({
      speaker_id,
      role: (index ? "prospect" : "you") as string | null,
      role_source: "confirmed",
      display_name: index ? "Fictional Buyer" : "Fictional Seller",
      icon: null as string | null,
    })),
  };
}
function response() {
  return new Response(JSON.stringify(data), {
    headers: { etag: `"call-label-${data.user_revision}"` },
  });
}
function Probe() {
  const { profiles, canSave } = useSpeakerProfiles(CALL);
  return <output data-can-save={canSave}>{JSON.stringify(profiles)}</output>;
}
async function render(scope = "first", enabled = true, source = transcript) {
  await act(async () =>
    root.render(
      <SpeakerServerProfiles
        key={scope}
        callId={CALL}
        transcriptRevision={transcript.revision}
        enabled={enabled}
      >
        <Probe />
        <CallMap
          callId={CALL}
          transcript={source}
          report={fixture.report as SalesReport}
          durationMs={transcript.duration_ms}
          onSeek={() => {}}
          onSelectEvidence={() => {}}
        />
      </SpeakerServerProfiles>,
    ),
  );
}
const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === text,
  )!;
const input = () =>
  host.querySelector<HTMLInputElement>('[role="dialog"] input')!;
const puts = () =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
async function edit() {
  await act(async () =>
    host
      .querySelectorAll<HTMLButtonElement>(
        '[aria-label="Speakers"] > button',
      )[1]
      .click(),
  );
}
async function type(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input(), value);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  data = initial();
  rejectPut = undefined;
  pendingPut = undefined;
  fetchMock = vi.fn<typeof fetch>(async (_url, init) => {
    if (init?.method === "PUT") {
      if (rejectPut) return new Response(null, { status: rejectPut });
      if (pendingPut) return pendingPut;
      const body = JSON.parse(init.body as string);
      data = {
        ...data,
        user_revision: data.user_revision + 1,
        status: "confirmed",
        speakers: body.speakers.map((s: Record<string, unknown>) => ({
          ...s,
          role_source: "confirmed",
        })),
      };
    }
    return response();
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it.each(["unavailable", "empty predicted"])(
  "keeps an older call with an %s map quiet and retries when details become ready",
  async (state) => {
    data.status = state === "unavailable" ? "unavailable" : "predicted";
    data.transcript_revision =
      state === "unavailable" ? null : transcript.revision;
    data.unavailable_reason =
      state === "unavailable" ? "transcript_not_ready" : null;
    data.user_revision = 0;
    data.speakers = [];
    await render();
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.textContent).toContain("Speaker names not set yet");
    expect(host.querySelector("output")!.dataset.canSave).toBe("false");
    expect(host.querySelector("output")!.textContent).toBe("{}");
    expect(host.querySelector('[aria-label="Speakers"]')).not.toBeNull();
    await edit();
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(puts()).toHaveLength(0);
    data = initial();
    await act(async () => button("Reload speaker details").click());
    expect(host.textContent).not.toContain("Speaker names not set yet");
    expect(host.querySelector("output")!.dataset.canSave).toBe("true");
    expect(host.querySelector("output")!.textContent).toContain(
      "Fictional Buyer",
    );
    await edit();
    expect(input().value).toBe("Fictional Buyer");
  },
);

it.each(["submission", "revision", "etag"])(
  "keeps a populated map fenced by its %s binding",
  async (field) => {
    const malformed = { ...data };
    if (field === "submission") malformed.submission_id = "another-call";
    if (field === "revision")
      malformed.transcript_revision = "another-revision";
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(malformed), {
        headers: {
          etag: field === "etag" ? '"call-label-0"' : '"call-label-1"',
        },
      }),
    );
    await render();
    expect(host.querySelector("output")!.textContent).toBe("{}");
    expect(host.querySelector("output")!.dataset.canSave).toBe("false");
    expect(host.querySelector('[role="alert"]')).toBeNull();
  },
);

it("writes once on Save, waits for confirmation and reads the result in a fresh session", async () => {
  await render();
  await edit();
  await type("Updated Buyer");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        'button[aria-label="Carpentry & building"]',
      )!
      .click(),
  );
  expect(puts()).toHaveLength(0);
  let resolve!: (r: Response) => void;
  pendingPut = new Promise((r) => {
    resolve = r;
  });
  await act(async () => button("Save").click());
  expect(button("Saving…").disabled).toBe(true);
  expect(host.querySelector("output")!.textContent).not.toContain(
    "Updated Buyer",
  );
  expect(localStorage.getItem(key)).toBeNull();
  const init = puts()[0][1]!;
  expect(init).toMatchObject({
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { "If-Match": '"call-label-1"' },
  });
  const body = JSON.parse(init.body as string);
  expect(body.transcript_revision).toBe(transcript.revision);
  expect(body.speakers).toHaveLength(ids.length);
  expect(body.speakers[1]).toMatchObject({
    display_name: "Updated Buyer",
    icon: "carpentry",
  });
  data.user_revision++;
  data.speakers[1].display_name = "Updated Buyer";
  data.speakers[1].icon = "carpentry";
  await act(async () => resolve(response()));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  await render("fresh session");
  expect(host.querySelector("output")!.textContent).toContain("Updated Buyer");
  expect(host.querySelector("output")!.textContent).toContain("carpentry");
  expect(puts()).toHaveLength(1);
  expect(host.textContent).not.toContain("Saved on this device");
});

it("uses legacy choices only as an unsaved prefill, keeps predictions unconfirmed and clears legacy after Save", async () => {
  data.user_revision = 0;
  data.status = "predicted";
  data.speakers.forEach((s) => {
    s.role_source = "predicted";
  });
  localStorage.setItem(
    key,
    JSON.stringify({
      [ids[1]]: { name: "Old local name", role: "prospect", icon: "carpentry" },
    }),
  );
  await render();
  expect(host.querySelector("output")!.textContent).not.toContain(
    "Old local name",
  );
  expect(host.querySelector("output")!.textContent).toContain('"role":null');
  await edit();
  expect(input().value).toBe("Old local name");
  await act(async () => button("Cancel").click());
  expect(puts()).toHaveLength(0);
  expect(localStorage.getItem(key)).not.toBeNull();
  await edit();
  await act(async () => button("Save").click());
  expect(localStorage.getItem(key)).toBeNull();
  expect(host.querySelector("output")!.textContent).toContain("Old local name");
});

it("refreshes a conflicting ETag and retains the draft for an explicit retry", async () => {
  await render();
  await edit();
  await type("My unsaved draft");
  rejectPut = 409;
  data.user_revision = 2;
  data.speakers[1].display_name = "Changed elsewhere";
  await act(async () => button("Save").click());
  expect(input().value).toBe("My unsaved draft");
  expect(host.textContent).toContain("changed elsewhere");
  expect(host.querySelector("output")!.textContent).toContain(
    "Changed elsewhere",
  );
  rejectPut = undefined;
  await act(async () => button("Save").click());
  expect(puts()[1][1]!.headers).toMatchObject({ "If-Match": '"call-label-2"' });
});

it("does not publish failed or malformed acknowledgements", async () => {
  await render();
  await edit();
  await type("Unsaved Buyer");
  rejectPut = 503;
  await act(async () => button("Save").click());
  expect(input().value).toBe("Unsaved Buyer");
  expect(host.querySelector("output")!.textContent).not.toContain(
    "Unsaved Buyer",
  );
  expect(button("Save").disabled).toBe(false);
  rejectPut = undefined;
  pendingPut = Promise.resolve(
    new Response(JSON.stringify({ ...data, transcript_revision: "wrong" }), {
      headers: { etag: '"call-label-1"' },
    }),
  );
  await act(async () => button("Save").click());
  expect(input().value).toBe("Unsaved Buyer");
  expect(host.querySelector("output")!.textContent).not.toContain(
    "Unsaved Buyer",
  );
});

it("ignores a late write after the report/session is discarded and suppresses guest fallback", async () => {
  await render();
  await edit();
  await type("Old session draft");
  let resolve!: (r: Response) => void;
  pendingPut = new Promise((r) => {
    resolve = r;
  });
  await act(async () => button("Save").click());
  const signal = puts()[0][1]!.signal!;
  await render("signed out", false);
  expect(signal.aborted).toBe(true);
  data.speakers[1].display_name = "Old session draft";
  await act(async () => resolve(response()));
  expect(host.querySelector("output")!.textContent).toBe("{}");
  expect(localStorage.getItem(key)).toBeNull();
});

it("removes legacy speaker details only after server-confirmed logout", async () => {
  localStorage.setItem(key, "legacy");
  localStorage.setItem("unrelated", "keep");
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }));
  await expect(requestSalesXrayLogout()).rejects.toThrow();
  expect(localStorage.getItem(key)).toBe("legacy");
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
  await requestSalesXrayLogout();
  expect(localStorage.getItem(key)).toBeNull();
  expect(localStorage.getItem("unrelated")).toBe("keep");
});

it("requires an explicit role for an unresolved third speaker before sending the full list", async () => {
  data.speakers.push({
    speaker_id: "third",
    display_name: "Fictional Third",
    role: null,
    role_source: "predicted",
    icon: null,
  });
  await render("three voices", true, {
    ...transcript,
    segments: [
      ...transcript.segments,
      { ...transcript.segments[0], id: "third-line", speaker_id: "third" },
    ],
  });
  await edit();
  expect(button("Save").disabled).toBe(true);
  expect(puts()).toHaveLength(0);
  const select = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Role for Fictional Third"]',
  )!;
  await act(async () => {
    select.value = "other";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => button("Save").click());
  expect(JSON.parse(puts()[0][1]!.body as string).speakers).toHaveLength(3);
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});
