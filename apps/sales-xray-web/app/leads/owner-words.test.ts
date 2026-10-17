import { describe, expect, it } from "vitest";

import { firstCallWords, ownerNote } from "./owner-words";

describe("who a lead is with, in plain words", () => {
  it("rewords the lead rules' notes", () => {
    expect(ownerNote("0 open leads (fewest)")).toBe(
      "Picked automatically because they had the fewest open leads.",
    );
    expect(ownerNote("1 open lead")).toBe(
      "Picked automatically because they were the only seller who could take it.",
    );
    expect(ownerNote("Speaks Hindi, covers Pune, 2 open leads (fewest)")).toBe(
      "Picked automatically because they speak Hindi, cover Pune and had the fewest open leads.",
    );
    expect(
      ownerNote(
        "Nobody free sells this product, speaks Hindi, 1 open lead (fewest)",
      ),
    ).toBe(
      "Picked automatically because they speak Hindi and had the fewest open leads. Nobody free sells this product.",
    );
    expect(
      ownerNote("Nobody free speaks Tamil; 3 open leads, the fewest."),
    ).toBe(
      "Picked automatically: nobody free speaks Tamil, so it went to whoever had the fewest open leads.",
    );
  });

  it("says who moved it and why it moved on", () => {
    expect(ownerNote("Moved by Suyash Kulkarni")).toBe(
      "Reassigned by Suyash Kulkarni.",
    );
    expect(ownerNote("No call in 15 minutes. 0 open leads (fewest)")).toBe(
      "Moved on after 15 min with no call. Picked automatically because they had the fewest open leads.",
    );
  });

  it("keeps notes that already read well, and has none for nothing", () => {
    const back = "Returning lead: back to Priya, who handled it before.";
    expect(ownerNote(back)).toBe(back);
    expect(ownerNote(null)).toBeNull();
    expect(ownerNote("  ")).toBeNull();
  });

  it("says how fast the first call came", () => {
    expect(firstCallWords(null, "2 h ago")).toBe(
      "Not called yet · came in 2 h ago",
    );
    expect(firstCallWords(0, "")).toBe("Called within a minute of coming in");
    expect(firstCallWords(5, "")).toBe("Called 5 min after it came in");
    expect(firstCallWords(130, "")).toBe("Called 2 hours after it came in");
    expect(firstCallWords(60 * 24 * 3, "")).toBe(
      "Called 3 days after it came in",
    );
  });
});
