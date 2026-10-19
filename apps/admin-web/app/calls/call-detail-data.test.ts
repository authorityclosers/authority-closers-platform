import { expect, it } from "vitest";

import {
  normalizeCallDetail,
  objectFacets,
  placeStages,
} from "./call-detail-data";

const RAW = {
  schema: "call-data-detail/1",
  taxonomy_version: "call-taxonomy/2",
  call: {
    recording_id: "9dba800c-11de-4564-9e4c-e8b0f2bdfca6",
    state: "ready",
    media_ms: 210_000,
    cost_inr: 3.7,
    tenant_id: "t-1",
    organisation: { id: "t-1", name: "Fictional Org", kind: "customer" },
    rep: {
      person_id: "p-1",
      label: "Fictional Rep",
      email: "rep@example.test",
    },
    language: "en",
    environment: "development",
  },
  stages: [
    { key: "received", label: "Received", status: "done", duration_ms: 0 },
    {
      key: "fast",
      label: "Fast pipeline",
      status: "done",
      cost_inr: 0.92,
      attempts: 1,
      tokens_in: 2514,
      tokens_out: 2075,
    },
    { key: "future_stage", label: "Something new", status: "not_built" },
    { key: "deep", label: "Deep pipeline", status: "mystery" },
  ],
  edges: [
    {
      from: "transcription",
      to: "fast",
      branch: "fast",
      status: "done",
      cost_inr: 0.92,
      duration_ms: 12_300,
    },
  ],
  runs: [
    { run_id: "r-1", pipeline: "fast", version: "fast/1", state: "uncertain" },
  ],
  objects: [
    {
      object_id: "o-1",
      type: "need",
      display: "More site visits",
      current: true,
    },
    { object_id: "o-2", type: "need", display: "Old wording", current: false },
    { object_id: "o-3", type: "objection", display: "Price", retracted: true },
    {
      object_id: "o-4",
      type: "people",
      display: "Erased name",
      erased: true,
      decisions: [{ decision: "accepted", actor: "Dipak", lead_written: true }],
    },
  ],
  totals: {
    call: { cost_inr: 3.7, tokens_in: 6190, tokens_out: 5472 },
    fast: { cost_inr: 0.92, tokens_in: 2514, tokens_out: 2075 },
  },
  facts: [],
  segments: [],
  voice: null,
};

it("reads the call header with the organisation's kind and the rep", () => {
  const detail = normalizeCallDetail(RAW);
  expect(detail.call.organisation).toEqual({
    id: "t-1",
    name: "Fictional Org",
    kind: "customer",
  });
  expect(detail.call.rep).toEqual({
    label: "Fictional Rep",
    email: "rep@example.test",
  });
  expect(detail.call.environment).toBe("development");
  expect(detail.taxonomyVersion).toBe("call-taxonomy/2");
});

it("keeps stage tokens and attempts, and treats unknown statuses as waiting", () => {
  const detail = normalizeCallDetail(RAW);
  expect(detail.stages[1]).toMatchObject({
    attempts: 1,
    tokensIn: 2514,
    tokensOut: 2075,
  });
  expect(detail.stages[3].status).toBe("waiting");
  const { placed, extra } = placeStages(detail.stages);
  expect(placed.map((stage) => stage.key)).toEqual([
    "received",
    "fast",
    "deep",
  ]);
  expect(extra.map((stage) => stage.key)).toEqual(["future_stage"]);
});

it("gives every object one state and counts them for the filters", () => {
  const detail = normalizeCallDetail(RAW);
  expect(detail.objects.map((object) => object.state)).toEqual([
    "current",
    "superseded",
    "retracted",
    "erased",
  ]);
  expect(detail.objects[3].decisions).toEqual([
    {
      decision: "accepted",
      actor: "Dipak",
      at: null,
      question: null,
      leadField: null,
      leadWritten: true,
    },
  ]);
  const facets = objectFacets(detail.objects);
  expect(facets.types).toEqual([
    ["need", 2],
    ["objection", 1],
    ["people", 1],
  ]);
});

it("reads totals per branch, zero where the server sends none", () => {
  const detail = normalizeCallDetail(RAW);
  expect(detail.totals.call).toEqual({
    costInr: 3.7,
    tokensIn: 6190,
    tokensOut: 5472,
  });
  expect(detail.totals.deep).toEqual({ costInr: 0, tokensIn: 0, tokensOut: 0 });
  expect(detail.edges[0]).toMatchObject({ branch: "fast", durationMs: 12_300 });
  expect(detail.runs[0].state).toBe("uncertain");
});
