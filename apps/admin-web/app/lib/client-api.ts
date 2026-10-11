/**
 * Browser commands to the admin API: same-origin /v1 paths only, the page's
 * Origin (the API requires it on cookie writes) and one Idempotency-Key per
 * intent, so a retried click never repeats a change. Never throws.
 */
export type CommandResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

const SAFE_PATH = /^\/v1\/[A-Za-z0-9\-._~/%]*$/;

function problemMessage(status: number, body: unknown): string {
  const detail =
    typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail: unknown }).detail
      : null;
  if (typeof detail === "string" && detail.length < 300) return detail;
  if (status === 401) return "Your session has ended. Sign in again.";
  if (status === 403) return "Your account can't make this change.";
  if (status === 409) return "This changed meanwhile. Reload and try again.";
  if (status === 422) return "Check the details and try again.";
  return "The change wasn't confirmed. Try again.";
}

export async function command<T>(
  path: string,
  body: unknown,
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<CommandResult<T>> {
  if (!SAFE_PATH.test(path) || path.includes(".."))
    return { ok: false, status: 400, message: "This action isn't available." };
  let response: Response;
  try {
    response = await fetcher(path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        origin: window.location.origin,
        "idempotency-key": idempotencyKey,
      },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, message: "No connection. Try again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok)
    return {
      ok: false,
      status: response.status,
      message: problemMessage(response.status, payload),
    };
  return { ok: true, data: payload as T };
}

export const newKey = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/** One command's idempotency key and the request body it was made for. */
export type Intent = { key: string; body: string };

/**
 * The key for this request: the same key when the body is unchanged (a retry
 * is recognised and never applied twice), a new key once it was edited (so a
 * changed request isn't refused as "changed meanwhile").
 */
export function keyFor(previous: Intent | null, body: unknown): Intent {
  const text = JSON.stringify(body);
  return previous && previous.body === text
    ? previous
    : { key: newKey(), body: text };
}
