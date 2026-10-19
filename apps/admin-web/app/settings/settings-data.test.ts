import { expect, it } from "vitest";

import { normalizeCallData } from "../sales-xray/call-data-model";
import { normalizeReportSettings } from "../sales-xray/report-settings-data";
import {
  analysisArea,
  callDataArea,
  executionArea,
  providerArea,
  reportArea,
} from "./settings-data";

const ok = <T>(data: T) => ({ ok: true as const, data });

it("lists each step's provider and model and the paid policy", () => {
  const area = providerArea(
    ok({
      execution_activated: true,
      current: {
        revision: 7,
        created_at: "2026-10-18T10:00:00Z",
        configuration: {
          policy: { allow_paid: true },
          routes: [
            {
              task: "conversation_facts",
              provider_id: "gemini",
              model_id: "gemini-3.8-flash",
              prompt_revision: "facts-v2",
            },
          ],
        },
      },
    }),
  );
  expect(area.unavailable).toBeNull();
  expect(area.revision).toBe("7");
  expect(area.changedAt).toBe("2026-10-18T10:00:00Z");
  expect(area.rows).toEqual([
    { label: "Hosted AI", value: "Switched on" },
    { label: "Paid providers", value: "Allowed" },
    {
      label: "Conversation facts",
      value: "gemini · gemini-3.8-flash",
      note: "facts-v2",
    },
  ]);
});

it("names analysis settings in words, with the report language spelled out", () => {
  const area = analysisArea(
    ok({
      revision: 3,
      created_at: null,
      settings: {
        c4_max_requests: 8,
        c4_max_completion_tokens: 2000,
        c5_max_completion_tokens: 6000,
        c5_output_profile: "detailed",
        c5_coaching_prompt_revision: "coaching-v5",
        report_language_default: "hi-Deva+en",
      },
    }),
  );
  expect(area.rows.map((row) => [row.label, row.value])).toEqual([
    ["Facts: most AI requests per call", "8"],
    ["Facts: longest answer", "2,000 tokens"],
    ["Report: longest answer", "6,000 tokens"],
    ["Report detail", "Detailed"],
    ["Coaching prompt", "coaching-v5"],
    ["Report language", "Hindi and English"],
  ]);
  expect(area.changedAt).toBeNull();
});

it("shows running or paused, the budget and calls waiting", () => {
  const area = executionArea(
    ok({
      control: {
        revision: 2,
        paused: false,
        changed_at: "2026-10-17T08:00:00Z",
      },
      budget: {
        cap_paise: 3_000_000,
        available_paise: 1_250_050,
        warning: "warning",
      },
      waiting_calls: 4,
    }),
  );
  expect(area.rows.map((row) => [row.label, row.value, row.note])).toEqual([
    ["Analyses", "Running", undefined],
    ["AI budget", "₹30,000", undefined],
    ["Left", "₹12,501", "Warning"],
    ["Calls waiting for budget", "4", undefined],
  ]);
});

it("summarises both call data pipelines with today's spend", () => {
  const area = callDataArea(
    ok(
      normalizeCallData({
        revision: 5,
        config: {
          fast: {
            enabled: true,
            model: "gemini-3.8-flash",
            daily_cap_inr: 300,
          },
          deep: { enabled: false, model: "gemini-3.8-pro", daily_cap_inr: 150 },
          streaming: { provider: "", model: "" },
        },
        spent_today_inr: { fast: 12.5, deep: 0 },
        history: [{ revision: 5, at: "2026-10-19T02:00:00Z" }],
      }),
    ),
  );
  expect(area.revision).toBe("5");
  expect(area.changedAt).toBe("2026-10-19T02:00:00Z");
  expect(area.rows[0]).toEqual({
    label: "Fast pipeline",
    value: "On · gemini-3.8-flash · ₹300 a day",
    note: "₹12.50 spent today",
  });
  expect(area.rows[1].value).toBe("Off");
  expect(area.rows[2]).toEqual({
    label: "Live transcription",
    value: "Not set",
    note: undefined,
  });
});

it("says which report version everyone and each organisation uses", () => {
  const area = reportArea(
    ok(
      normalizeReportSettings({
        general_version_number: null,
        versions: [{ number: 1, label: "Version 1" }],
        industries: [],
        organisations: [
          {
            tenant_id: "t1",
            name: "Fictional Org",
            version_number: 1,
            own_version_number: null,
          },
          {
            tenant_id: "t2",
            name: "Other Org",
            version_number: 1,
            own_version_number: 1,
          },
        ],
        history: [],
      }),
    ),
  );
  expect(area.rows.map((row) => [row.label, row.value])).toEqual([
    ["Everyone uses", "Version 1"],
    ["Saved versions", "1"],
    ["Industry defaults", "None"],
    ["Organisations with their own version", "1 of 2"],
  ]);
});

it("keeps an area that could not be read, with the reason and no rows", () => {
  const area = executionArea({
    ok: false,
    error: "Not available to this account.",
  });
  expect(area.unavailable).toBe("Not available to this account.");
  expect(area.rows).toEqual([]);
  expect(area.href).toBe("/sales-xray/execution");
});
