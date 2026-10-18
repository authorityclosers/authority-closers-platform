import { expect, it } from "vitest";

import { autoCallTitle } from "./call-auto-title";

// Summaries in the shape the report writes them (names are fictional).
it.each([
  [
    "You conducted an exploratory conversation with Nitesh, owner of Bloom and Building Material Enterprise, diagnosing that his business is constrained by credit.",
    "Nitesh · Bloom and Building Material Enterprise",
  ],
  [
    "You conducted an objective discovery and scoping discussion with Taveera Services, clarifying decision-making roles.",
    "Taveera Services",
  ],
  [
    "You conducted a crisp discovery conversation with Daryl Pell, sales operations lead at Brindle Cart. You explored their lead handoff issues.",
    "Daryl Pell · Brindle Cart",
  ],
  [
    "You conducted an informative, advisory consultation with Balasaheb regarding environmental permissions for a poultry unit in Satara.",
    "Balasaheb · Environmental permissions",
  ],
  [
    "Ankita spoke with Mr. Mishra regarding digital marketing services for his real estate business.",
    "Mr. Mishra · Digital marketing services",
  ],
  [
    "You conducted a focused commercial and qualification conversation with Ira Ransurikar. You clarified key commercial boundaries.",
    "Call with Ira Ransurikar",
  ],
  [
    "You held an informative advisory conversation covering MPCB pollution licensing for a planned electroplating business.",
    "MPCB pollution licensing",
  ],
  [
    "You qualified key project parameters for Rohit's 63-unit studio apartment pre-launch in Baner.",
    "Call with Rohit",
  ],
  [
    "Synthetic test call. Arun Alva discussed Fastener Batch for Pravah Hill Engineering Works Private Limited. The conversation ended as Won.",
    "Pravah Hill Engineering Works Private Limited",
  ],
])("names the call from its summary: %s", (summary, title) => {
  expect(autoCallTitle(summary)).toBe(title);
});

it.each([
  [null],
  [""],
  // Nothing clear to name it after: the dated default stays.
  [
    "You qualified operational friction around handoffs in separate sheets and established an agreed follow-up meeting.",
  ],
  [
    "You reviewed loan sanction procedures and calculated own-contribution requirements based on an 85% builder demand milestone.",
  ],
  // A Hindi or Marathi summary keeps the default name.
  ["मानस ने खंडेला में सूट का बिज़नेस चलाने वाले प्रोस्पेक्ट से बात की।"],
])("keeps the default name when nothing clear is said: %s", (summary) => {
  expect(autoCallTitle(summary)).toBeNull();
});

it("never exceeds the 80-character title", () => {
  const title = autoCallTitle(
    "You spoke with Asha regarding " +
      "very long topic words ".repeat(2) +
      "today.",
  );
  expect(title === null || [...title].length <= 80).toBe(true);
  const company = autoCallTitle(
    `You met ${"Alpha ".repeat(30)}Services today.`,
  );
  expect(company === null || [...company].length <= 80).toBe(true);
});
