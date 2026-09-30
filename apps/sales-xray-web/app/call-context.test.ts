import { expect, it } from "vitest";

import { businessNamed, firstEntity, prospectBusiness } from "./call-context";

const texts = [
  "You pivoted from asking operational questions to pitching the 3-day Leadership Funnel Program.",
  "It surfaced 15 to 20 lakh of unpaid receivables and their revenue.",
];

it("names what was sold and the money talked about, from the report's words", () => {
  expect(firstEntity(texts, "program")).toBe("3-day Leadership Funnel Program");
  expect(firstEntity(texts, "money", /\d/)).toBe("15 to 20 lakh");
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
  ).toBe("carpentry");
  expect(businessNamed("We run a furniture business in Pune.")?.key).toBe(
    "carpentry",
  );
  expect(businessNamed("They talked about the event and coaching.")).toBeNull();
});

it("takes the business only from evidence about the prospect", () => {
  const roles = { seller: "s", prospect: "p" };
  // The seller naming the prospect's business to them counts.
  expect(
    prospectBusiness(
      [
        {
          speaker_id: "s",
          text: "आपका यहां पे शायद carpentry का business है right?",
        },
      ],
      roles,
    )?.key,
  ).toBe("carpentry");
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
  // Without confirmed roles, nothing.
  expect(
    prospectBusiness(
      [{ speaker_id: "p", text: "हमारा furniture business है" }],
      null,
    ),
  ).toBeNull();
});
