/** Every topic and category has a colour by its meaning (Home's finish, 15 Nov 2026). */
import { expect, it } from "vitest";

import { CATEGORIES, FEATURED } from "./library";
import { CATEGORY_TONES, FEATURED_TONES } from "./tones";

const TONES = ["good", "info", "action", "calls"];

it("gives each of the home's topics and Dipak's categories a meaning's colour", () => {
  for (const topic of FEATURED)
    expect(TONES).toContain(FEATURED_TONES[topic.id]);
  for (const category of CATEGORIES)
    expect(TONES).toContain(CATEGORY_TONES[category.id]);
  expect(Object.keys(FEATURED_TONES).sort()).toEqual(
    FEATURED.map((topic) => topic.id).sort(),
  );
  expect(Object.keys(CATEGORY_TONES).sort()).toEqual(
    CATEGORIES.map((category) => category.id).sort(),
  );
});
