/**
 * The queue's filters live in the address (/calls?status=ready&organisation=…),
 * so reload, back and shared links keep the view. This turns page search
 * params into the API query, dropping anything malformed. Pure.
 */
import { CALL_STATUSES, type CallStatus } from "./call-data";
import { REVIEW_STATES, type ReviewState } from "./labels-data";

export type QueueFilters = {
  review?: ReviewState;
  status?: CallStatus;
  organisation?: string;
  rep?: string;
  language?: string;
  provider?: string;
  prompt?: string;
  since?: string;
  until?: string;
  cursor?: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const PROVIDER = /^[A-Za-z0-9._:-]{1,64}$/;
const PROMPT = /^[A-Za-z0-9._:+-]{1,128}$/;
const CURSOR = /^[A-Za-z0-9_-]{1,64}$/;
const LANGUAGES = new Set(["en", "hi-Deva+en", "mr-Deva+en"]);

type Params = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value;

export function queueFilters(params: Params): QueueFilters {
  const filters: QueueFilters = {};
  const review = one(params.review);
  if (REVIEW_STATES.includes(review as ReviewState))
    filters.review = review as ReviewState;
  const status = one(params.status);
  if (CALL_STATUSES.includes(status as CallStatus))
    filters.status = status as CallStatus;
  for (const key of ["organisation", "rep"] as const) {
    const value = one(params[key]);
    if (value && UUID.test(value)) filters[key] = value.toLowerCase();
  }
  const language = one(params.language);
  if (language && LANGUAGES.has(language)) filters.language = language;
  const provider = one(params.provider);
  if (provider && PROVIDER.test(provider)) filters.provider = provider;
  const prompt = one(params.prompt);
  if (prompt && PROMPT.test(prompt)) filters.prompt = prompt;
  for (const key of ["since", "until"] as const) {
    const value = one(params[key]);
    if (value && DAY.test(value) && !Number.isNaN(Date.parse(value)))
      filters[key] = value;
  }
  const cursor = one(params.cursor);
  if (cursor && CURSOR.test(cursor)) filters.cursor = cursor;
  return filters;
}

/** URLSearchParams in a stable order; `omit` drops keys (e.g. the cursor for a new filter). */
export function filterQuery(
  filters: QueueFilters,
  omit: (keyof QueueFilters)[] = [],
): string {
  const query = new URLSearchParams();
  for (const key of [
    "review",
    "status",
    "organisation",
    "rep",
    "language",
    "provider",
    "prompt",
    "since",
    "until",
    "cursor",
  ] as const) {
    const value = filters[key];
    if (value && !omit.includes(key)) query.set(key, value);
  }
  return query.toString();
}

/** The API path for one queue page. */
export const queueApiPath = (filters: QueueFilters, limit = 50) => {
  const query = filterQuery(filters);
  return `/v1/admin/conversation/calls?${query ? `${query}&` : ""}limit=${limit}`;
};
