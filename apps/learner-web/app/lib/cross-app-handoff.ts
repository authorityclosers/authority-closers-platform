export const HANDOFF_VERIFIER_KEY = "reflex.handoff.verifier";

/** Exact local destination; reject unsafe input instead of repairing it. */
export function isHandoffReturnPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    [...value].length <= 512 &&
    !/[\\\u0000-\u001f\u007f-\u009f]/.test(value)
  );
}

export function handoffReturnPath(value: unknown): string {
  return isHandoffReturnPath(value) ? value : "/home";
}

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function createHandoffVerifier(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

export async function handoffChallenge(verifier: string): Promise<string> {
  return base64url(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)),
    ),
  );
}
