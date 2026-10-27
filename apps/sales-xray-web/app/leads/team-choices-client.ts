/**
 * Who a seller fits (owner bug #49, 27 Oct 2026; Lead OS's /team/choices): the
 * areas, languages and products already on this organisation's leads, with
 * how many leads each, and how many of last month's leads a profile would
 * take. Owners and managers only. A chip saves its value exactly as given;
 * chips are compared by key, the same normalisation allocation uses.
 */

const BASE = "/v1/lead-desk/team/choices";

export type Choice = Readonly<{ value: string; key: string; leads: number }>;

export type Choices = Readonly<{
  days: number;
  leads: number;
  areas: Choice[];
  languages: Choice[];
  products: Choice[];
  industry: Readonly<{ id: string; name: string }> | null;
}>;

export type Fit = Readonly<{
  days: number;
  leads: number;
  fits: number;
  percent: number;
  by: Readonly<{ language: number; area: number; product: number }>;
}>;

export type Profile = {
  languages: string[];
  areas: string[];
  products: string[];
};

const choice = (value: unknown): Choice | null => {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  return typeof item.value === "string" &&
    typeof item.key === "string" &&
    typeof item.leads === "number"
    ? { value: item.value, key: item.key, leads: item.leads }
    : null;
};

const list = (value: unknown): Choice[] =>
  Array.isArray(value)
    ? value.map(choice).filter((item): item is Choice => item !== null)
    : [];

/** This organisation's choices; null where the server doesn't offer them. */
export async function readChoices(
  signal?: AbortSignal,
): Promise<Choices | null> {
  const response = await fetch(`${BASE}?days=90`, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) return null;
  const body = (await response.json()) as Record<string, unknown>;
  const industry = body.industry as Record<string, unknown> | null;
  return {
    days: typeof body.days === "number" ? body.days : 90,
    leads: typeof body.leads === "number" ? body.leads : 0,
    areas: list(body.areas),
    languages: list(body.languages),
    products: list(body.products),
    industry:
      industry &&
      typeof industry.id === "string" &&
      typeof industry.name === "string"
        ? { id: industry.id, name: industry.name }
        : null,
  };
}

/** How many of last month's leads this profile would take; nothing is saved. */
export async function readFit(
  profile: Profile,
  signal?: AbortSignal,
): Promise<Fit | null> {
  const response = await fetch(`${BASE}/fit`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify(profile),
    signal,
  });
  if (!response.ok) return null;
  const body = (await response.json()) as Partial<Fit>;
  return typeof body.fits === "number" &&
    typeof body.leads === "number" &&
    typeof body.percent === "number"
    ? {
        days: body.days ?? 30,
        leads: body.leads,
        fits: body.fits,
        percent: body.percent,
        by: {
          language: body.by?.language ?? 0,
          area: body.by?.area ?? 0,
          product: body.by?.product ?? 0,
        },
      }
    : null;
}

/** An area's or a product's key: lower case, hyphens as spaces, one space. */
export function placeKey(value: string): string {
  return value
    .toLocaleLowerCase()
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** The languages a seller can pick, each in its own script (a fixed list). */
export const LANGUAGES: readonly Readonly<{
  code: string;
  name: string;
  native: string;
}>[] = [
  { code: "hi", name: "Hindi", native: "हिन्दी" },
  { code: "mr", name: "Marathi", native: "मराठी" },
  { code: "en", name: "English", native: "English" },
  { code: "gu", name: "Gujarati", native: "ગુજરાતી" },
  { code: "bn", name: "Bengali", native: "বাংলা" },
  { code: "ta", name: "Tamil", native: "தமிழ்" },
  { code: "te", name: "Telugu", native: "తెలుగు" },
  { code: "kn", name: "Kannada", native: "ಕನ್ನಡ" },
  { code: "ml", name: "Malayalam", native: "മലയാളം" },
  { code: "pa", name: "Punjabi", native: "ਪੰਜਾਬੀ" },
  { code: "or", name: "Odia", native: "ଓଡ଼ିଆ" },
  { code: "ur", name: "Urdu", native: "اردو" },
];

/** A saved language's key: its code where the list knows it, else its words. */
export function languageKey(value: string): string {
  const words = value.trim().toLocaleLowerCase();
  return (
    LANGUAGES.find(
      (item) =>
        item.code === words ||
        item.name.toLocaleLowerCase() === words ||
        item.native === value.trim(),
    )?.code ?? words
  );
}
