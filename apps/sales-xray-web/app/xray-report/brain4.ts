import type { ReportEvidence } from "../report-contract";
import type { Line } from "../report-story-model";

/**
 * Brain 4.0 (the coaching lead's 18-skill rubric, brain4.py) as the API saves it
 * beside the pointers: `report.structure.brain4`. Always a beta (AC-SVAL gates):
 * the app never rates anything itself and shows only what checks out here.
 */

export type Brain4Dimension = {
  id: string;
  number: number;
  label: string;
  category: string;
  /** 1-5, or null for "–" (not needed on this call, or not enough evidence). */
  rating: number | null;
  applicability: "applicable" | "not_applicable" | "not_enough_evidence";
  observed: string | null;
  coaching: string | null;
  /** How sure the read is; it never changes the rating (rubric). */
  confidence: "high" | "medium" | "low" | null;
  /** D07 only: PASS, WARN or FAIL. */
  ethicsGate: "PASS" | "WARN" | "FAIL" | null;
  evidence: ReportEvidence[];
};

export type Brain4Category = {
  id: string;
  label: string;
  rated: number;
  of: number;
  /** The category's mean rating, when enough of it is rated; never an official score. */
  score: number | null;
};

export type Brain4View = {
  version: string;
  calibration: string | null;
  /** How many of the 18 skills the call gave enough to rate. */
  rated: number;
  callType: string | null;
  ethicsGate: Brain4Dimension["ethicsGate"];
  categories: Brain4Category[];
  dimensions: Brain4Dimension[];
};

type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, max = 600) =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : null;
const GATES = ["PASS", "WARN", "FAIL"] as const;
const CONFIDENCE = ["high", "medium", "low"] as const;
const gate = (value: unknown) =>
  (GATES as readonly unknown[]).includes(value)
    ? (value as Brain4Dimension["ethicsGate"])
    : null;

export function readBrain4(
  value: unknown,
  evidence: (value: unknown) => ReportEvidence[],
): Brain4View | null {
  if (
    !isObject(value) ||
    value.status !== "beta" ||
    typeof value.version !== "string" ||
    !value.version.startsWith("brain4-review/")
  )
    return null;
  const items = Array.isArray(value.dimensions)
    ? value.dimensions.filter(isObject)
    : [];
  const dimensions: Brain4Dimension[] = items
    .map((item, index) => {
      // The calibrated rating when there is one, else the saved rating.
      const raw = Number.isInteger(item.shown_rating)
        ? item.shown_rating
        : item.rating;
      const rating =
        typeof raw === "number" && Number.isInteger(raw) && raw >= 1 && raw <= 5
          ? raw
          : null;
      const applicability: Brain4Dimension["applicability"] =
        rating !== null
          ? "applicable"
          : item.applicability === "not_applicable"
            ? "not_applicable"
            : "not_enough_evidence";
      return {
        id: text(item.id, 8) ?? "",
        number:
          typeof item.number === "number" && Number.isInteger(item.number)
            ? item.number
            : index + 1,
        label: text(item.label, 80) ?? "",
        category: text(item.category, 60) ?? "",
        rating,
        applicability,
        observed: text(item.observed, 400),
        coaching: rating !== null ? text(item.coaching, 300) : null,
        confidence:
          rating !== null &&
          (CONFIDENCE as readonly unknown[]).includes(item.confidence)
            ? (item.confidence as Brain4Dimension["confidence"])
            : null,
        ethicsGate: rating !== null ? gate(item.ethics_gate) : null,
        evidence: evidence(item.evidence).slice(0, 2),
      };
    })
    .filter((item) => /^D\d\d$/.test(item.id) && item.label);
  if (!dimensions.length) return null;
  const rollup = isObject(value.rollup) ? value.rollup : {};
  const categories = Array.isArray(rollup.categories)
    ? rollup.categories.filter(isObject).map((item) => ({
        id: text(item.id, 60) ?? "",
        label: text(item.label, 80) ?? "",
        rated: typeof item.rated === "number" ? item.rated : 0,
        of: typeof item.of === "number" ? item.of : 0,
        score:
          typeof item.score === "number" &&
          Number.isFinite(item.score) &&
          item.score >= 1 &&
          item.score <= 5
            ? item.score
            : null,
      }))
    : [];
  const calibration = isObject(value.calibration)
    ? text(value.calibration.revision, 80)
    : null;
  const callType = text(value.call_type, 40);
  return {
    version: value.version,
    calibration,
    rated: dimensions.filter((d) => d.rating !== null).length,
    callType: callType && callType !== "unknown" ? callType : null,
    ethicsGate: dimensions.find((d) => d.id === "D07")?.ethicsGate ?? null,
    categories: categories.filter((c) => c.id && c.label),
    dimensions,
  };
}

/** The band a rating reads as, in the Report's own status words. */
export function brain4Band(
  rating: number | null,
): "excellent" | "good" | "average" | "needs_improvement" | null {
  if (rating === null) return null;
  if (rating >= 5) return "excellent";
  if (rating === 4) return "good";
  if (rating === 3) return "average";
  return "needs_improvement";
}

/**
 * The Overview's two highlights from the 18 skills: the best-rated skill and what
 * happened in it, and the lowest-rated skill with its next-call coaching. Ties go to
 * the earlier skill. None when no skill qualifies.
 */
export function brain4Highlights(view: Brain4View): {
  strength: Line | null;
  improvement: Line | null;
} {
  const rated = view.dimensions.filter(
    (d): d is Brain4Dimension & { rating: number } => d.rating !== null,
  );
  const best = rated
    .filter((d) => d.rating >= 4 && d.observed)
    .reduce<
      (typeof rated)[number] | null
    >((top, d) => (top === null || d.rating > top.rating ? d : top), null);
  const worst = rated
    .filter((d) => d.rating <= 3 && d.coaching)
    .reduce<
      (typeof rated)[number] | null
    >((low, d) => (low === null || d.rating < low.rating ? d : low), null);
  return {
    strength: best
      ? { text: `${best.label}: ${best.observed}`, sources: best.evidence }
      : null,
    improvement: worst
      ? { text: `${worst.label}: ${worst.coaching}`, sources: worst.evidence }
      : null,
  };
}
