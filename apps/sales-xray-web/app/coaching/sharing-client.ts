/** Own-account sharing and focus feedback. Never throws. */

export type SharingView = {
  available: boolean;
  shared: boolean;
  revision: number;
  reaches: { name: string; why: "admin" }[];
};
export type Result<T> =
  | { data: T; error: null }
  | { data: null; error: string };

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown): value is string =>
  typeof value === "string" && !!value.trim();

export function parseSharing(raw: unknown): SharingView | null {
  const item = object(raw);
  if (
    typeof item.available !== "boolean" ||
    typeof item.shared !== "boolean" ||
    !Number.isSafeInteger(item.revision) ||
    (item.revision as number) < 0 ||
    !Array.isArray(item.reaches)
  )
    return null;
  return {
    available: item.available,
    shared: item.available && item.shared,
    revision: item.revision as number,
    reaches: item.reaches
      .map(object)
      .filter((row) => text(row.name) && row.why === "admin")
      .map((row) => ({ name: row.name as string, why: "admin" as const })),
  };
}

async function call<T>(
  path: string,
  parse: (raw: unknown) => T | null,
  init: RequestInit = {},
): Promise<Result<T>> {
  try {
    const response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: init.signal ?? AbortSignal.timeout(10000),
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (response.status === 409)
      return { data: null, error: "This changed elsewhere. Try again." };
    if (!response.ok)
      return {
        data: null,
        error:
          response.status === 401
            ? "Sign in again to continue."
            : response.status === 403
              ? "This isn't available in this workspace."
              : "Not saved. Try again.",
      };
    if (response.status === 204) return { data: parse(null) as T, error: null };
    const data = parse(await response.json());
    return data === null
      ? { data: null, error: "Coaching didn’t load. Try again." }
      : { data, error: null };
  } catch {
    return { data: null, error: "Coaching could not be reached. Try again." };
  }
}

export const readSharing = (signal?: AbortSignal) =>
  call("/v1/me/coaching/sharing", parseSharing, { signal });

export const changeSharing = (shared: boolean, expectedRevision: number) =>
  call("/v1/me/coaching/sharing", parseSharing, {
    method: "PUT",
    body: JSON.stringify({ shared, expected_revision: expectedRevision }),
  });

export const sendContext = (body: {
  command_id: string;
  focus_skill_id: string;
  mission_origin_submission_id: string;
  context: string;
}) =>
  call("/v1/me/coaching/context", () => true, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const sendFeedback = (body: {
  command_id: string;
  agreement: "agree" | "not_completely";
  focus_skill_id: string;
  mission_origin_submission_id: string;
}) =>
  call("/v1/me/coaching/feedback", () => true, {
    method: "POST",
    body: JSON.stringify(body),
  });
