import { afterEach, expect, it, vi } from "vitest";
import {
  companyBinding,
  companyId,
  fictionalCompanyPayload,
} from "./prospect-company.fixture";
import { saveCompanyFields } from "./prospect-company-save-client";

const city = { kind: "text", text: "Fictional पुणे" };
function acknowledgement() {
  return {
    schema: "ac.sales-xray.company/1",
    person_id: companyBinding.personId,
    tenant_id: companyBinding.tenantId,
    session_id: companyBinding.sessionId,
    company: {
      ...fictionalCompanyPayload(),
      revision: 3,
      fields: {
        ...fictionalCompanyPayload().fields,
        city: {
          state: "known",
          basis: "person",
          locked: true,
          set_at: "2026-10-11T10:00:00Z",
          value: { ...city },
        },
      },
    },
  };
}
function respond(payload: unknown = acknowledgement(), status = 200) {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(payload), { status }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
const save = (values: unknown = { city }, options = {}) =>
  saveCompanyFields(companyBinding, companyId, 2, values, options);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("saves literal human values once and accepts only a bound locked acknowledgement", async () => {
  const fetcher = respond();
  const result = await save();
  expect(result.status).toBe("saved");
  if (result.status === "saved") {
    expect(result.binding).toEqual(companyBinding);
    expect(result.company.fields.city).toMatchObject({
      basis: "person",
      locked: true,
      value: city,
    });
  }
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/conversation/companies/${companyId}/fields`,
    expect.objectContaining({
      method: "PUT",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      body: JSON.stringify({ fields: { city }, expected_revision: 2 }),
    }),
  );
});

it("acknowledges a human Unknown lock and an unchanged idempotent revision", async () => {
  const raw = acknowledgement();
  raw.company.revision = 2;
  const unknown = { kind: "unknown", reason: "not_asked" };
  Object.assign(raw.company.fields.city, {
    state: "unknown",
    reason: "not_asked",
  });
  respond(raw);
  const result = await save({ city: unknown });
  expect(result.status).toBe("saved");
  if (result.status === "saved") {
    expect(result.company.fields.city).toEqual({
      state: "unknown",
      reason: "not_asked",
      basis: "person",
      locked: true,
      set_at: "2026-10-11T10:00:00Z",
    });
    expect(result.company.fields.city).not.toHaveProperty("value");
  }
});

it.each(["person_id", "tenant_id", "session_id"])(
  "withholds a successful acknowledgement from a different %s",
  async (key) => {
    respond({ ...acknowledgement(), [key]: companyId });
    const result = await save();
    expect(result.status).toBe("unconfirmed");
    expect(result).not.toHaveProperty("company");
  },
);

it.each(["identity", "revision", "value", "basis", "lock", "unknown"])(
  "never reports saved when the acknowledgement has a different %s",
  async (kind) => {
    const raw = acknowledgement();
    if (kind === "identity") raw.company.company_id = companyBinding.personId;
    if (kind === "revision") raw.company.revision = 1;
    if (kind === "value") raw.company.fields.city.value.text = "Different";
    if (kind === "basis") raw.company.fields.city.basis = "heard_in_call";
    if (kind === "lock") raw.company.fields.city.locked = false;
    if (kind === "unknown") {
      Object.assign(raw.company.fields.city, {
        state: "unknown",
        reason: "not_mentioned",
      });
    }
    respond(raw);
    expect((await save()).status).toBe("unconfirmed");
  },
);

it.each([
  {},
  { city: null },
  { phone: city },
  { name: { kind: "unknown", reason: "not_asked" } },
  { city: { ...city, evidence: "private" } },
  { city: { kind: "numeric", lower: "8" } },
  { city: { kind: "text", text: " " } },
  { city: { kind: "text", text: "a\0b" } },
  { city: { kind: "text", text: "x".repeat(2049) } },
  { city: { kind: "unknown", reason: { toString: () => "not_asked" } } },
])(
  "refuses an invalid or non-human field command before any request",
  async (values) => {
    const fetcher = respond();
    expect((await save(values)).status).toBe("invalid");
    expect(fetcher).not.toHaveBeenCalled();
  },
);

it("rejects invalid identities, revisions and deadlines before a write", async () => {
  const fetcher = respond();
  for (const revision of [0, 1.5, Number.MAX_SAFE_INTEGER + 1])
    expect(
      (await saveCompanyFields(companyBinding, companyId, revision, { city }))
        .status,
    ).toBe("invalid");
  expect(
    (
      await saveCompanyFields(
        { ...companyBinding, sessionId: "no" },
        companyId,
        2,
        { city },
      )
    ).status,
  ).toBe("invalid");
  expect(
    (await saveCompanyFields(companyBinding, "../other", 2, { city })).status,
  ).toBe("invalid");
  expect((await save({ city }, { deadlineMs: 0 })).status).toBe("unconfirmed");
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([202, 302, 401, 403, 404, 409, 500])(
  "does not retry HTTP %s or expose its body as a saved fact",
  async (status) => {
    const fetcher = respond(acknowledgement(), status);
    expect((await save()).status).toBe(
      status === 409 ? "conflict" : "unconfirmed",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it.each(["json", "length", "stream", "network"])(
  "bounds or hides a %s failure and never repeats an uncertain write",
  async (kind) => {
    const fetcher = vi.fn().mockImplementation(() => {
      if (kind === "network") throw new Error("private details");
      return Promise.resolve(
        new Response(
          kind === "json" ? "private invalid JSON" : "x".repeat(131073),
          {
            headers: kind === "length" ? { "content-length": "131073" } : {},
          },
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    expect(await save()).toEqual({
      status: "unconfirmed",
      message: "This save could not be confirmed. Reload before saving again.",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it("bounds a stalled save and cancels the request without an automatic retry", async () => {
  vi.useFakeTimers();
  let signal!: AbortSignal;
  const fetcher = vi.fn((_, options) => {
    signal = options.signal;
    return new Promise(() => {});
  });
  vi.stubGlobal("fetch", fetcher);
  const result = save();
  await vi.advanceTimersByTimeAsync(2500);
  expect((await result).status).toBe("unconfirmed");
  expect(signal.aborted).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("does not start an already cancelled save", async () => {
  const fetcher = respond();
  const controller = new AbortController();
  controller.abort();
  expect((await save({ city }, { signal: controller.signal })).status).toBe(
    "unconfirmed",
  );
  expect(fetcher).not.toHaveBeenCalled();
});

it("detaches the requested values and actor scope before transport starts", async () => {
  const fetcher = respond();
  const binding = { ...companyBinding };
  const values = { city: { ...city } };
  const result = saveCompanyFields(binding, companyId, 2, values);
  binding.sessionId = companyId;
  values.city.text = "Changed after submission";
  expect((await result).status).toBe("saved");
  expect(fetcher.mock.calls[0][1].body).toBe(
    JSON.stringify({ fields: { city }, expected_revision: 2 }),
  );
});
