/**
 * The Feature catalogue's data: catalogue.generated.json, written by
 * scripts/catalogue/build_feature_catalogue.py from the code (anchors, pages,
 * API routes, releases on main) and the product words in feature_seed.json.
 * Pure helpers only, so the page, the Offer Studio and the tests share them.
 */
import generated from "./catalogue.generated.json";

export type FeatureStatus = "live" | "dev" | "planned";

export type Feature = Readonly<{
  id: string;
  name: string;
  product: string;
  category: string;
  value: string;
  for: readonly string[];
  details: readonly string[];
  switch: string | null;
  status: FeatureStatus;
  since: Readonly<{
    version: string;
    date: string;
    or_earlier: boolean;
  }> | null;
  anchors: readonly Readonly<{
    anchor: string;
    path: string;
    exists: boolean;
  }>[];
  api: Readonly<{ prefixes: readonly string[]; routes: number }>;
  fixture: string | null;
  preview: string | null;
  shots: Readonly<Record<string, string>>;
}>;

export type Category = Readonly<{
  id: string;
  name: string;
  line: string;
  icon: string;
}>;
export type Product = Readonly<{ id: string; name: string; line: string }>;

export type Catalogue = Readonly<{
  source: Readonly<{ commit: string; date: string; main: string }>;
  latest_release: Readonly<{
    version: string;
    date: string;
    title: string;
  }> | null;
  products: readonly Product[];
  categories: readonly Category[];
  audiences: readonly string[];
  features: readonly Feature[];
  counts: Readonly<Record<FeatureStatus, number>>;
  pages: readonly Readonly<{
    app: string;
    key: string;
    pages: number;
    fixtures: number;
    named: number;
    unnamed: readonly string[];
  }>[];
  api: Readonly<{
    routes: number;
    areas: readonly Readonly<{ prefix: string; routes: number }>[];
  }>;
  settings: readonly Readonly<{ area: string; entries: number }>[];
  switches: readonly string[];
  releases: readonly Readonly<{
    version: string;
    date: string;
    title: string;
  }>[];
}>;

export const CATALOGUE = generated as unknown as Catalogue;

export const STATUS_LABEL: Record<FeatureStatus, string> = {
  live: "Live",
  dev: "On dev",
  planned: "Planned",
};

export type StatusFilter = FeatureStatus | "all";

export type Filters = Readonly<{
  query: string;
  product: string;
  status: StatusFilter;
  audience: string;
}>;

export const NO_FILTERS: Filters = {
  query: "",
  product: "all",
  status: "all",
  audience: "all",
};

/** "Live since v0.83.0", "Live by v0.40.0", "Built, off" etc., for one badge. */
export function statusText(feature: Feature): string {
  if (feature.status === "live" && feature.since)
    return `${feature.since.or_earlier ? "By" : "Since"} ${feature.since.version}`;
  return STATUS_LABEL[feature.status];
}

function haystack(feature: Feature, catalogue: Catalogue): string {
  const category = catalogue.categories.find((c) => c.id === feature.category);
  const product = catalogue.products.find((p) => p.id === feature.product);
  return [
    feature.name,
    feature.value,
    ...feature.details,
    ...feature.for,
    feature.switch ?? "",
    category?.name ?? "",
    product?.name ?? "",
    feature.since?.version ?? "",
    STATUS_LABEL[feature.status],
  ]
    .join(" ")
    .toLowerCase();
}

/** Every word of the query must appear somewhere in the feature's words. */
export function filterFeatures(
  features: readonly Feature[],
  filters: Filters,
  catalogue: Catalogue = CATALOGUE,
): Feature[] {
  const words = filters.query.toLowerCase().split(/\s+/).filter(Boolean);
  return features.filter((feature) => {
    if (filters.product !== "all" && feature.product !== filters.product)
      return false;
    if (filters.status !== "all" && feature.status !== filters.status)
      return false;
    if (filters.audience !== "all" && !feature.for.includes(filters.audience))
      return false;
    if (!words.length) return true;
    const text = haystack(feature, catalogue);
    return words.every((word) => text.includes(word));
  });
}

/** Categories in the seed's order, each with its matching features; empty ones dropped. */
export function groupByCategory(
  features: readonly Feature[],
  catalogue: Catalogue = CATALOGUE,
): { category: Category; features: Feature[] }[] {
  return catalogue.categories
    .map((category) => ({
      category,
      features: features.filter((f) => f.category === category.id),
    }))
    .filter((group) => group.features.length > 0);
}

/** The best screenshot for a size and theme, falling back to the other theme. */
export function shotFor(
  feature: Feature,
  size: "390" | "1440",
  theme: "light" | "dark",
): string | null {
  const other = theme === "light" ? "dark" : "light";
  return (
    feature.shots[`${size}-${theme}`] ??
    feature.shots[`${size}-${other}`] ??
    null
  );
}

export function productName(id: string, catalogue: Catalogue = CATALOGUE) {
  return catalogue.products.find((p) => p.id === id)?.name ?? id;
}
