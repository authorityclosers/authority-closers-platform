// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { normalizeCallDetail } from "./call-detail-data";
import { StageTable } from "./stage-table";

const DETAIL = normalizeCallDetail({
  stages: [
    {
      key: "received",
      label: "Received",
      status: "done",
      started_at: "2026-10-20T09:00:00Z",
      finished_at: "2026-10-20T09:00:00Z",
    },
    {
      key: "audio_check",
      label: "Audio check",
      code: "C1",
      status: "done",
      started_at: "2026-10-20T09:00:00Z",
      finished_at: "2026-10-20T09:00:04Z",
      duration_ms: 4000,
    },
    {
      key: "facts",
      label: "Facts",
      code: "C4",
      status: "done",
      started_at: "2026-10-20T09:00:42Z",
      finished_at: "2026-10-20T09:01:10Z",
      duration_ms: 28_000,
      cost_inr: 0.42,
      provider: "gemini",
      model: "gemini-3.8-flash",
      attempts: 3,
      tokens_in: 3000,
      tokens_out: 600,
      detail: "3 tasks · 1 failed or unsure",
    },
    {
      key: "coaching",
      label: "Report, coaching",
      code: "C5",
      status: "running",
      started_at: "2026-10-20T09:01:11Z",
    },
    {
      key: "review",
      label: "Human review",
      status: "done",
      started_at: "2026-10-22T09:00:00Z",
      finished_at: "2026-10-22T09:30:00Z",
      detail: "4 answers from 1 reviewer",
    },
  ],
});

function render() {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<StageTable stages={DETAIL.stages} />);
  return host;
}

it("gives every stage one dense row: code, start, time, tokens, model and cost", () => {
  const host = render();
  const rows = [...host.querySelectorAll("tbody tr")];
  expect(rows).toHaveLength(5);
  const facts = rows[2].textContent ?? "";
  for (const part of [
    "C4",
    "Facts",
    "3 tasks · 1 failed or unsure",
    "3 attempts",
    "+42 s",
    "28.0 s",
    "3,000 / 600",
    "gemini · gemini-3.8-flash",
    "₹0.42",
  ])
    expect(facts).toContain(part);
  expect(rows[3].getAttribute("data-status")).toBe("running");
  expect(rows[3].textContent).toContain("+1:11");
});

it("keeps people's later stages off the timing scale and totals the cost", () => {
  const host = render();
  const review = [...host.querySelectorAll("tbody tr")][4];
  expect(review.textContent).toContain("+2 days");
  expect(review.textContent).toContain("after the run");
  // Received, audio check, facts and coaching draw a bar; review does not.
  expect(host.querySelectorAll("tbody span[style]")).toHaveLength(4);
  expect(host.querySelector("tfoot")?.textContent).toContain("₹0.42");
  expect(host.querySelector("tfoot")?.textContent).toContain("1 min 11 s");
});

it("shows the same stages as cards on phones", () => {
  const host = render();
  const cards = [...host.querySelectorAll('[role="list"] article')];
  expect(cards).toHaveLength(5);
  expect(cards[2].textContent).toContain("+42 s · 28.0 s · ₹0.42");
});
