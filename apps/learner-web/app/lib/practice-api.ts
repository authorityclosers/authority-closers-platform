import { z } from "zod";

const option = z.object({
  id: z.number().int().nonnegative(),
  text: z.string(),
});
const node = z.object({ buyer: z.string(), options: z.array(option) });
const summary = z.object({
  id: z.string().regex(/^[a-z0-9-]+$/),
  version: z.number().int(),
  title: z.string(),
  kind: z.enum(["choice", "gap", "match", "build", "order", "audio", "branch"]),
  skill: z.string(),
  description: z.string(),
  art: z.string().regex(/^[a-z-]+$/),
  color: z.string(),
  estimated_minutes: z.number(),
  item_count: z.number().int(),
});
const promptBase = { id: z.string(), prompt: z.string(), hint: z.string() };
const prompt = z.discriminatedUnion("kind", [
  z.object({
    ...promptBase,
    kind: z.literal("choice"),
    options: z.array(option),
  }),
  z.object({ ...promptBase, kind: z.literal("gap"), options: z.array(option) }),
  z.object({
    ...promptBase,
    kind: z.literal("match"),
    left: z.array(option),
    options: z.array(option),
  }),
  z.object({
    ...promptBase,
    kind: z.literal("build"),
    options: z.array(option),
  }),
  z.object({
    ...promptBase,
    kind: z.literal("order"),
    options: z.array(option),
  }),
  z.object({
    ...promptBase,
    kind: z.literal("audio"),
    options: z.array(option),
    spoken: z.string(),
    audio_url: z.string().regex(/^\/arcade-v02\/listen-0[1-3]\.wav$/),
  }),
  z.object({ ...promptBase, kind: z.literal("branch"), node }),
]);
const catalog = z.discriminatedUnion("mode", [
  z.object({
    mode: z.literal("editorial_preview"),
    items: z.array(summary),
    course_progress_affected: z.literal(false),
    responses_stored: z.literal(false),
  }),
  z.object({
    mode: z.literal("published"),
    items: z.array(summary),
    course_progress_affected: z.literal(false),
    responses_stored: z.literal(true),
  }),
]);
const set = summary.extend({
  mode: z.enum(["editorial_preview", "published"]),
  items: z.array(prompt).min(1),
});
// The persisted engine pins this same public content shape. Its stricter
// boundary must not silently discard unknown answer or policy fields.
const strictOption = option.strict();
const strictNode = node.strict().extend({ options: z.array(strictOption) });
const strictPrompt = z.discriminatedUnion("kind", [
  prompt.options[0].strict().extend({ options: z.array(strictOption) }),
  prompt.options[1].strict().extend({ options: z.array(strictOption) }),
  prompt.options[2]
    .strict()
    .extend({ left: z.array(strictOption), options: z.array(strictOption) }),
  prompt.options[3].strict().extend({ options: z.array(strictOption) }),
  prompt.options[4].strict().extend({ options: z.array(strictOption) }),
  prompt.options[5].strict().extend({ options: z.array(strictOption) }),
  prompt.options[6].strict().extend({ node: strictNode }),
]);
export const practiceSetSchema = set
  .strict()
  .extend({ items: z.array(strictPrompt).min(1) });
export const practiceCatalogSchema = catalog;
export const practiceNodeSchema = strictNode;
const checked = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("continue"), node }),
  z.object({
    kind: z.literal("feedback"),
    reference_match: z.boolean().nullable(),
    explanation: z.string(),
    course_progress_affected: z.literal(false),
    responses_stored: z.literal(false),
  }),
]);
export type PracticeSummary = z.infer<typeof summary>;
export type PracticeSet = z.infer<typeof set>;
export type PracticePrompt = z.infer<typeof prompt>;
export type PracticeCheckResult = z.infer<typeof checked>;
export type PracticeNode = z.infer<typeof node>;

export class PracticeRequestError extends Error {
  constructor(public readonly status: number) {
    super(
      status === 401
        ? "Sign in to open Practice Arcade."
        : status === 403
          ? "Select your academy to open practice."
          : status === 404
            ? "This practice set isn’t available here yet."
            : "Practice couldn’t connect. Your choices are still here—try again.",
    );
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  signal: AbortSignal,
  body?: unknown,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timeout = setTimeout(abort, 12_000);
  try {
    const response = await fetch(`/v1/practice/${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      mode: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
      headers: {
        accept: "application/json",
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new PracticeRequestError(response.status);
    return schema.parse(await response.json());
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", abort);
  }
}
export const practiceApi = {
  catalog: (signal: AbortSignal) => request("sets", catalog, signal),
  set: (id: string, signal: AbortSignal) =>
    request(`sets/${encodeURIComponent(id)}`, set, signal),
  check: (
    setId: string,
    itemId: string,
    selections: number[],
    signal: AbortSignal,
  ) =>
    request(`sets/${encodeURIComponent(setId)}/check`, checked, signal, {
      item_id: itemId,
      selections,
    }),
};
export type PracticeApi = typeof practiceApi;
