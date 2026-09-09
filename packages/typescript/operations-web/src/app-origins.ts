const origins = new Set([
  "http://coach.localhost:3102",
  "https://coach-staging.authorityclosers.com",
  "https://coach.authorityclosers.com",
]);
/** Deployment-owned exact target; never browser return_url/Host inference. */
export function coachAppOrigin(
  value: string | undefined,
  runtime: string | undefined,
): string | null {
  if (!value || !origins.has(value)) return null;
  if (runtime === "production" && value.startsWith("http:")) return null;
  return value;
}
