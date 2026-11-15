/**
 * Each topic's colour by its meaning, never by its place (Home's finish, owner,
 * 15 Nov 2026; the kit's --sx-tone-*): good = the outcome, info =
 * understanding the customer and yourself, action = what needs doing,
 * calls = talking and connecting.
 */
export type Tone = "good" | "info" | "action" | "calls";

/** The home's four topics. */
export const FEATURED_TONES: Readonly<Record<string, Tone>> = {
  talk: "calls",
  discover: "info",
  price: "action",
  close: "good",
};

/** Dipak's ten categories. */
export const CATEGORY_TONES: Readonly<Record<string, Tone>> = {
  "01": "info", // Sales Mindset & Psychology
  "02": "calls", // Rapport Building & Trust
  "03": "calls", // Communication & Listening
  "04": "info", // Problem & Desire Discovery
  "05": "good", // Value Creation & Quantification
  "06": "info", // Qualification & Decision Process
  "07": "good", // Solution Presentation & Influence
  "08": "action", // Objection Handling & Negotiation
  "09": "good", // Closing & Follow-Up
  "10": "action", // Sales Growth & Performance
};

export const toneOfFeatured = (id: string): Tone =>
  FEATURED_TONES[id] ?? "good";

export const toneOfCategory = (id: string): Tone =>
  CATEGORY_TONES[id] ?? "good";
