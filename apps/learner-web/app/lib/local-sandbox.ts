/** Presentation/transport opt-in only. The local API still verifies every session. */
export const LOCAL_SANDBOX_ORIGIN = "http://learner.localhost:3100";

export function isLocalSandboxMediaUrl(
  url: URL,
  browserOrigin: string | null = typeof window === "undefined"
    ? null
    : window.location.origin,
): boolean {
  return (
    process.env.NODE_ENV === "development" &&
    process.env.NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED === "true" &&
    browserOrigin === LOCAL_SANDBOX_ORIGIN &&
    url.origin === LOCAL_SANDBOX_ORIGIN &&
    !url.username &&
    !url.password &&
    !url.hash &&
    url.pathname.startsWith("/v1/media/playback/")
  );
}
