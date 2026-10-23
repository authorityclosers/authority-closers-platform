import { describe, expect, it } from "vitest";

import {
  CATALOGUE,
  NO_FILTERS,
  filterFeatures,
  groupByCategory,
  shotFor,
  statusText,
  type Feature,
} from "./catalogue-data";

const feature = (patch: Partial<Feature>): Feature => ({
  id: "x",
  name: "Chats inbox",
  product: "sales-xray",
  category: "chats",
  value: "WhatsApp, Messenger and Instagram in one inbox.",
  for: ["Sellers"],
  details: [],
  switch: null,
  status: "live",
  since: { version: "v0.70.0", date: "2026-10-21", or_earlier: false },
  anchors: [],
  api: { prefixes: [], routes: 0 },
  fixture: null,
  preview: null,
  shots: {},
  ...patch,
});

describe("the generated catalogue", () => {
  it("names a known category, product and status for every feature", () => {
    const categories = new Set(CATALOGUE.categories.map((c) => c.id));
    const products = new Set(CATALOGUE.products.map((p) => p.id));
    expect(CATALOGUE.features.length).toBeGreaterThan(50);
    for (const f of CATALOGUE.features) {
      expect(categories.has(f.category), f.id).toBe(true);
      expect(products.has(f.product), f.id).toBe(true);
      expect(["live", "dev", "planned"]).toContain(f.status);
      if (f.status === "live") expect(f.since?.version, f.id).toMatch(/^v0/);
    }
  });

  it("counts match the features", () => {
    for (const status of ["live", "dev", "planned"] as const)
      expect(CATALOGUE.counts[status]).toBe(
        CATALOGUE.features.filter((f) => f.status === status).length,
      );
  });

  it("never shows a price or cost word as a feature's value to sellers", () => {
    // Prices live only in the Offer Studio's internal tiers.
    for (const f of CATALOGUE.features)
      expect(f.value, f.id).not.toMatch(/₹\s?\d|\$\s?\d/);
  });
});

describe("filterFeatures", () => {
  const list = [
    feature({ id: "a" }),
    feature({
      id: "b",
      name: "Cost meter",
      value: "Rupees per minute",
      category: "admin",
      product: "admin",
      for: ["AC staff"],
      status: "dev",
      since: null,
    }),
  ];

  it("matches every word anywhere in the feature's words", () => {
    expect(
      filterFeatures(list, { ...NO_FILTERS, query: "whatsapp inbox" }).map(
        (f) => f.id,
      ),
    ).toEqual(["a"]);
    expect(
      filterFeatures(list, { ...NO_FILTERS, query: "whatsapp cost" }),
    ).toEqual([]);
  });

  it("filters by status, product and audience", () => {
    expect(
      filterFeatures(list, { ...NO_FILTERS, status: "dev" }).map((f) => f.id),
    ).toEqual(["b"]);
    expect(
      filterFeatures(list, { ...NO_FILTERS, product: "admin" }).map(
        (f) => f.id,
      ),
    ).toEqual(["b"]);
    expect(
      filterFeatures(list, { ...NO_FILTERS, audience: "Sellers" }).map(
        (f) => f.id,
      ),
    ).toEqual(["a"]);
  });

  it("groups in the seed's category order and drops empty groups", () => {
    const groups = groupByCategory(list);
    const order = CATALOGUE.categories.map((c) => c.id);
    expect(groups.map((g) => g.category.id)).toEqual(
      ["chats", "admin"].sort((x, y) => order.indexOf(x) - order.indexOf(y)),
    );
  });
});

describe("labels and shots", () => {
  it("says since, by (history starts there) or the plain status", () => {
    expect(statusText(feature({}))).toBe("Since v0.70.0");
    expect(
      statusText(
        feature({
          since: { version: "v0.40.0", date: "2026-10-11", or_earlier: true },
        }),
      ),
    ).toBe("By v0.40.0");
    expect(statusText(feature({ status: "planned", since: null }))).toBe(
      "Planned",
    );
  });

  it("falls back to the other theme's screenshot", () => {
    const f = feature({ shots: { "390-dark": "/d.webp" } });
    expect(shotFor(f, "390", "light")).toBe("/d.webp");
    expect(shotFor(f, "1440", "light")).toBeNull();
  });
});
