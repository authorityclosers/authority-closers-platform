import { afterEach, expect, it, vi } from "vitest";
import {
  parseProfileFields,
  profileValueText,
} from "./prospect-profile-contract";
import { editProspectField, parseProspectSummary } from "./prospects-client";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";

afterEach(() => vi.unstubAllGlobals());

it("opens legacy summaries and preserves observed source bounds, human locks and contradictions", () => {
  const legacy = { ...syntheticProspect, profile_fields: undefined };
  expect(parseProspectSummary(legacy).profile_fields).toBeUndefined();
  const fields = parseProfileFields(syntheticProspect.profile_fields);
  expect(fields.name).toMatchObject({
    basis: "heard_in_call",
    evidence: { quote: "माझं नाव अदिती आहे.", start_ms: 1000 },
  });
  expect(fields.business).toMatchObject({
    locked: true,
    basis: "person",
    heard_differently: [{ value: { text: "Example company two" } }],
  });
  if (fields.budget?.state !== "known") throw new Error("missing budget");
  expect(profileValueText(fields.budget.value)).toBe(
    "Approximately [2–3) lakh INR per year",
  );
});

it.each(["phone", "email"])("rejects AI-heard %s even with evidence", (key) => {
  expect(() =>
    parseProfileFields({ [key]: syntheticProspect.profile_fields!.name }),
  ).toThrow("prospect_profile_invalid");
});

it.each([
  { locked: true },
  { evidence: undefined },
  {
    evidence: {
      segment_id: "s1",
      quote: "test",
      submission_id: "other",
      start_ms: 1,
      end_ms: 2,
    },
  },
])("rejects invalid heard source or lock metadata %j", (change) => {
  expect(() =>
    parseProfileFields({
      name: { ...syntheticProspect.profile_fields!.name, ...change },
    }),
  ).toThrow();
});

it.each([
  { lower: "NaN" },
  { upper: null },
  { lower_inclusive: "true" },
  { unit: "people" },
])("rejects malformed numeric values %j", (change) => {
  const budget = syntheticProspect.profile_fields!.budget!;
  if (budget.state !== "known") throw new Error("missing budget");
  expect(() =>
    parseProfileFields({
      budget: { ...budget, value: { ...budget.value, ...change } },
    }),
  ).toThrow();
});

it("sends a typed human edit with the current revision and checks the acknowledged lock", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        schema: "ac.sales-xray.prospect-fields/1",
        prospect: {
          prospect_id: syntheticProspect.prospect_id,
          revision: 4,
          profile_fields: {
            phone: {
              state: "known",
              basis: "person",
              locked: true,
              set_at: "2026-10-10T01:00:00Z",
              value: { kind: "text", text: "Test phone" },
            },
          },
        },
      }),
      { status: 200 },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  await editProspectField(
    syntheticProspect.prospect_id,
    3,
    "phone",
    "Test phone",
  );
  expect(fetch).toHaveBeenCalledWith(
    `/v1/conversation/prospects/${syntheticProspect.prospect_id}/fields`,
    expect.objectContaining({
      method: "PUT",
      credentials: "same-origin",
      redirect: "error",
    }),
  );
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    expected_revision: 3,
    fields: { phone: { kind: "text", text: "Test phone" } },
  });
});

it("fails a stale edit without retrying or overwriting", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 409 }));
  vi.stubGlobal("fetch", fetch);
  await expect(
    editProspectField(syntheticProspect.prospect_id, 3, "business", "Test"),
  ).rejects.toThrow("Reload");
  expect(fetch).toHaveBeenCalledOnce();
});

it("accepts a supplied Changed source and rejects it behind a person lock", () => {
  const field = syntheticProspect.profile_fields!.name!;
  if (field.state !== "known" || !field.evidence)
    throw new Error("missing source");
  const candidate = {
    ...field,
    changed_from: {
      value: { kind: "text", text: "Earlier" },
      evidence: { ...field.evidence, quote: "Earlier" },
      set_at: "2026-10-09T00:00:00Z",
    },
  };
  expect(parseProfileFields({ name: candidate }).name).toMatchObject({
    changed_from: { value: { text: "Earlier" } },
  });
  expect(() =>
    parseProfileFields({
      name: { ...candidate, basis: "person", locked: true },
    }),
  ).toThrow();
  expect(() =>
    parseProfileFields({
      name: {
        ...candidate,
        changed_from: {
          ...candidate.changed_from,
          set_at: "2026-10-11T00:00:00Z",
        },
      },
    }),
  ).toThrow();
});
