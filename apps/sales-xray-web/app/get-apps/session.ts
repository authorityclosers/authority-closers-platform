/** Use AC's canonical session check, including expiry and revocation. */
export async function sessionStatus(
  cookie: string | null,
): Promise<200 | 401 | 503> {
  if (!cookie) return 401;
  try {
    const origin = new URL(process.env.AC_CONVERSATION_API_ORIGIN ?? "");
    if (
      !["http:", "https:"].includes(origin.protocol) ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    )
      return 503;
    const response = await fetch(new URL("/v1/me/workspaces", origin), {
      headers: { cookie, accept: "application/json" },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    if (response.status === 401) return 401;
    if (!response.ok) return 503;
    const identity = await response.json();
    return typeof identity?.person_id === "string" &&
      typeof identity?.session_id === "string"
      ? 200
      : 503;
  } catch {
    return 503;
  }
}
