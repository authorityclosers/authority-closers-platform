export const SURFACE_STATE_ORDER = [
  "DEFAULT",
  "LOADING",
  "EMPTY",
  "ERROR_RETRYABLE",
  "ERROR_TERMINAL",
  "OFFLINE",
  "PERMISSION_DENIED",
  "LOCKED",
  "PARTIAL",
  "SUCCESS_FEEDBACK",
] as const;

export type SurfaceState = (typeof SURFACE_STATE_ORDER)[number];

export type QueryValue = string | string[] | undefined;

const surfaceStates = new Set<string>(SURFACE_STATE_ORDER);

export function isSurfaceStateSimulationEnabled(
  environment: string | undefined,
): boolean {
  return environment !== "production";
}

export function parseSurfaceState(
  value: QueryValue,
  environment: string | undefined = process.env.NODE_ENV,
): SurfaceState {
  if (!isSurfaceStateSimulationEnabled(environment)) return "DEFAULT";
  const candidate = Array.isArray(value) ? value[0] : value;
  const normalized = candidate?.trim().replace(/-/g, "_").toUpperCase();

  return normalized && surfaceStates.has(normalized)
    ? (normalized as SurfaceState)
    : "DEFAULT";
}

export function isContentVisible(state: SurfaceState): boolean {
  return (
    state === "DEFAULT" || state === "PARTIAL" || state === "SUCCESS_FEEDBACK"
  );
}

export function stateQuery(path: string, state: SurfaceState): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}state=${state.toLowerCase()}`;
}
