import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CallContext,
  businessNamed,
  firstEntity,
  nextStepValue,
  programMentionLabel,
  prospectBusiness,
} from "./call-context";
import type { SalesReport, Transcript } from "./report-contract";
import { SPEAKER_ICONS } from "./speaker-icons";

const texts = [
  "You pivoted from asking operational questions to pitching the 3-day Leadership Funnel Program.",
  "It surfaced 15 to 20 lakh of unpaid receivables and their revenue.",
];

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.setItem(
    "ac.xray.speakers.v1:business-attribution",
    JSON.stringify({
      seller: { name: "Seller", role: "salesperson", icon: null },
      prospect: { name: "Prospect", role: "prospect", icon: null },
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.removeItem("ac.xray.speakers.v1:business-attribution");
});

it("names what was sold and the money talked about, from the report's words", () => {
  expect(firstEntity(texts, "program")).toBe("3-day Leadership Funnel Program");
  expect(firstEntity(texts, "money", /\d/)).toBeNull();
});

it("labels a prospect's already-attended webinar as a neutral mention", () => {
  const text = "The prospect says they already attend a webinar.";
  expect(firstEntity([text], "program")).toBe("webinar");
  expect(programMentionLabel()).toBe("Mentioned");
});

it("says nothing when the report never mentioned it", () => {
  expect(firstEntity(["They asked about the program."], "program")).toBeNull();
  expect(firstEntity(["Their revenue grew."], "money", /\d/)).toBeNull();
});

it("names the business only when the call says it outright", () => {
  expect(
    businessNamed(
      "अच्छा ठीक है, आपका यहां पे शायद carpentry का business है right?",
    )?.key,
  ).toBeUndefined();
  expect(businessNamed("We run a furniture business in Pune.")?.key).toBe(
    "carpentry",
  );
  expect(businessNamed("I run a carpentry business.")?.key).toBe("carpentry");
  expect(businessNamed("मेरा carpentry का business है।")?.key).toBe(
    "carpentry",
  );
  expect(
    businessNamed(
      "I run an online business. My brother runs a carpentry business.",
    ),
  ).toBeNull();
  expect(businessNamed("We have never owned a carpentry business.")).toBeNull();
  expect(businessNamed("They talked about the event and coaching.")).toBeNull();
  expect(businessNamed("My brother runs a carpentry business.")).toBeNull();
  expect(
    businessNamed("Is your carpentry business still operating?"),
  ).toBeNull();
});

it("rejects third-party, negated and questioned business candidates", () => {
  expect(SPEAKER_ICONS).toHaveLength(53);
  for (const icon of SPEAKER_ICONS) {
    for (const keyword of icon.keywords) {
      expect(
        businessNamed(
          `I run an online business and my brother runs a ${keyword} business.`,
        ),
      ).toBeNull();
      expect(businessNamed(`मेरा ${keyword} का business नहीं है।`)).toBeNull();
      expect(businessNamed(`Do I run a ${keyword} business?`)).toBeNull();
    }
  }
  expect(
    businessNamed(
      "I run an online business and my brother runs a carpentry business",
    ),
  ).toBeNull();
  expect(businessNamed("मेरा carpentry का business नहीं है।")).toBeNull();
  expect(businessNamed("Do I run a carpentry business?")).toBeNull();
});

it("does not put a sale outcome under Next step", () => {
  expect(nextStepValue(null, "no_sale", null)).toBeNull();
  expect(nextStepValue(null, "disqualified", null)).toBeNull();
  expect(nextStepValue(null, "follow_up", "Friday")).toBe("Follow-up Friday");
  expect(nextStepValue("Call again Friday", "no_sale", null)).toBe(
    "Call again Friday",
  );
});

it("keeps glance controls visible until the compact row hides them", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "call-context.module.css"),
    "utf8",
  );
  expect(css).toContain("opacity: clamp(0, calc(1 - var(--fold, 0)), 1);");
  expect(css).toMatch(
    /\[data-report-sticky\]\[data-compact\] \.context\s*\{[^}]*visibility:\s*hidden;[^}]*pointer-events:\s*none;/s,
  );
});

it("takes the business only from evidence about the prospect", () => {
  const roles = { seller: "s", prospect: "p" };
  // A seller question does not establish the prospect's business.
  expect(
    prospectBusiness(
      [
        {
          speaker_id: "s",
          text: "आपका यहां पे शायद carpentry का business है right?",
        },
      ],
      roles,
    ),
  ).toBeNull();
  // The prospect's own words count.
  expect(
    prospectBusiness(
      [{ speaker_id: "p", text: "हमारा furniture business है" }],
      roles,
    )?.key,
  ).toBe("carpentry");
  // The seller's own business does not.
  expect(
    prospectBusiness(
      [{ speaker_id: "s", text: "I also run a furniture business." }],
      roles,
    ),
  ).toBeNull();
  expect(
    prospectBusiness(
      [{ speaker_id: "p", text: "My brother runs a carpentry business." }],
      roles,
    ),
  ).toBeNull();
  // Without confirmed roles, nothing.
  expect(
    prospectBusiness(
      [{ speaker_id: "p", text: "हमारा furniture business है" }],
      null,
    ),
  ).toBeNull();
});

it("does not render an inferred business for quoted or hypothetical ownership", async () => {
  const transcript = {
    duration_ms: 10_000,
    segments: [
      {
        speaker_id: "prospect",
        start_ms: 0,
        end_ms: 5_000,
        text: 'My brother told me, "I run a carpentry business."',
      },
      {
        speaker_id: "prospect",
        start_ms: 5_000,
        end_ms: 10_000,
        text: "If I run a carpentry business, I will need new tools.",
      },
      {
        speaker_id: "seller",
        start_ms: 9_000,
        end_ms: 10_000,
        text: "Understood.",
      },
    ],
  } as unknown as Transcript;
  const report = { summary: "", verdict: "" } as unknown as SalesReport;

  await act(async () =>
    root.render(
      createElement(CallContext, {
        callId: "business-attribution",
        report,
        transcript,
      }),
    ),
  );

  const glance = host.querySelector('[aria-label="This call at a glance"]');
  expect(glance).not.toBeNull();
  expect(glance?.textContent).not.toContain("Business");
  expect(glance?.textContent).not.toContain("carpentry");
});
