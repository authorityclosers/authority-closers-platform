/**
 * The upload terms a person agreed to, per workspace, in this browser (owner,
 * 26 Oct 2026: "once a seller has accepted the terms, don't show them again
 * for that workspace"). Only the exact policy agreed to counts: a newer policy
 * asks again. The box still shows, ticked, and unticking it forgets the
 * agreement. Nothing leaves this browser.
 */

const KEY = "sales-xray:upload-terms";

function read(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, string>)
      : {};
  } catch {
    return {};
  }
}

function write(next: Record<string, string>) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: the person ticks the box each time, as before */
  }
}

/** The policy this workspace's person agreed to here, if any. */
export function agreedTerms(tenantId: string | null): string | null {
  if (!tenantId) return null;
  const sha = read()[tenantId];
  return typeof sha === "string" && sha ? sha : null;
}

/** Remember the agreement to this exact policy for the workspace. */
export function rememberTerms(tenantId: string | null, policySha: string) {
  if (!tenantId || !policySha) return;
  write({ ...read(), [tenantId]: policySha });
}

/** Unticked: the next upload in this workspace asks again. */
export function forgetTerms(tenantId: string | null) {
  if (!tenantId) return;
  const next = read();
  delete next[tenantId];
  write(next);
}
