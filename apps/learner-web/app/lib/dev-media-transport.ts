/** Transport-only local QA mapping. This never validates or grants access. */
export const DEVELOPMENT_MEDIA_STAGING_ORIGIN =
  "https://staging.authorityclosers.com";
export const DEVELOPMENT_MEDIA_PREFIX = "/v1/media/playback/";
export const DEVELOPMENT_MEDIA_REGISTRATION = "/v1/dev-bridge/media";
export const DEVELOPMENT_MEDIA_LOCATOR_PREFIX = `${DEVELOPMENT_MEDIA_REGISTRATION}/`;
export const DEVELOPMENT_MEDIA_MAX_SOURCES = 12;
export const DEVELOPMENT_MEDIA_MAX_BYTES = 8 * 1024 * 1024 * 1024;

const OPAQUE_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const TOKEN_QUERY = /^\?token=AC-MEDIA\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/;

/** Exact serialized key grammar emitted by the application delivery signer. */
export function isDevelopmentMediaObjectUrl(url: URL): boolean {
  if (
    url.username ||
    url.password ||
    url.hash ||
    !url.pathname.startsWith(DEVELOPMENT_MEDIA_PREFIX)
  )
    return false;
  if (
    url.search.length > 4096 + "?token=".length ||
    !TOKEN_QUERY.test(url.search)
  )
    return false;
  const encoded = url.pathname.slice(DEVELOPMENT_MEDIA_PREFIX.length);
  let key: string;
  try {
    key = decodeURIComponent(encoded);
  } catch {
    return false;
  }
  if (
    !key ||
    key.length > 512 ||
    key.includes("..") ||
    encodeURIComponent(key) !== encoded
  )
    return false;
  const parts = key.split("/");
  if (
    parts.length < 7 ||
    parts[0] !== "tenants" ||
    parts[2] !== "media" ||
    parts.some((part) => !OPAQUE_SEGMENT.test(part))
  )
    return false;
  // No manifest forwarding or child URL rewriting in this progressive-only slice.
  return !/\.m3u8$/i.test(parts.at(-1)!);
}

export function isDevelopmentMediaRange(value: string | null): boolean {
  if (value === null) return true;
  if (value.length > 64) return false;
  const match = /^bytes=(0|[1-9]\d*)-((?:0|[1-9]\d*)?)$/.exec(value);
  if (!match) return false;
  const start = Number(match[1]);
  const end = match[2] === "" ? null : Number(match[2]);
  return (
    Number.isSafeInteger(start) &&
    start < DEVELOPMENT_MEDIA_MAX_BYTES &&
    (end === null ||
      (Number.isSafeInteger(end) &&
        end >= start &&
        end < DEVELOPMENT_MEDIA_MAX_BYTES))
  );
}

function exactLoopbackOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    const loopback =
      ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.hostname.endsWith(".localhost");
    return loopback &&
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !url.hash &&
      !url.search &&
      url.pathname === "/" &&
      url.origin === value
      ? url.origin
      : null;
  } catch {
    return null;
  }
}

/**
 * Call only after the original HTTPS descriptor passed the existing media and
 * expiry checks. Null withholds unsupported transport; never fall back to the
 * original URL when this opted-in bridge cannot map it. No token is persisted.
 */
export function developmentMediaRegistrationUrl(
  configuredBrowserOrigin: string,
  currentBrowserOrigin: string | null,
): string | null {
  const origin = exactLoopbackOrigin(configuredBrowserOrigin);
  return origin && currentBrowserOrigin === origin
    ? `${origin}${DEVELOPMENT_MEDIA_REGISTRATION}`
    : null;
}

export function isDevelopmentMediaLocatorPath(path: string): boolean {
  return new RegExp(
    `^${DEVELOPMENT_MEDIA_LOCATOR_PREFIX}[A-Za-z0-9_-]{43}$`,
  ).test(path);
}

/** Untrusted metadata can only withhold transport; upstream verifies signatures. */
export function readDevelopmentMediaSource(
  approvedHttpsSource: string,
  now = Date.now(),
): { expiresAt: number } | null {
  if (
    typeof approvedHttpsSource !== "string" ||
    approvedHttpsSource.length > 8192
  )
    return null;
  try {
    const url = new URL(approvedHttpsSource);
    if (
      url.origin !== DEVELOPMENT_MEDIA_STAGING_ORIGIN ||
      url.href !== approvedHttpsSource ||
      !isDevelopmentMediaObjectUrl(url)
    )
      return null;
    const encoded = url.searchParams.get("token")!.split(".")[1];
    const binary = atob(
      encoded
        .replace(/-/g, "+")
        .replace(/_/g, "/")
        .padEnd(Math.ceil(encoded.length / 4) * 4, "="),
    );
    if (
      btoa(binary)
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "") !== encoded
    )
      return null;
    const claims = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(
        Uint8Array.from(binary, (character) => character.charCodeAt(0)),
      ),
    ) as Record<string, unknown>;
    if (
      !claims ||
      Array.isArray(claims) ||
      typeof claims !== "object" ||
      claims.typ !== "AC-MEDIA" ||
      claims.token_type !== "playback" ||
      !Number.isSafeInteger(claims.iat) ||
      !Number.isSafeInteger(claims.exp) ||
      (claims.iat as number) < 0 ||
      (claims.exp as number) <= (claims.iat as number) ||
      (claims.exp as number) - (claims.iat as number) > 3600 ||
      !Number.isSafeInteger((claims.exp as number) * 1000) ||
      (claims.iat as number) * 1000 > now + 30_000 ||
      (claims.exp as number) * 1000 <= now ||
      claims.key !==
        decodeURIComponent(
          url.pathname.slice(DEVELOPMENT_MEDIA_PREFIX.length),
        ) ||
      [
        "activity_id",
        "activity_version",
        "asset_id",
        "version_id",
        "binding_id",
        "enrollment_id",
        "delivery_grant_id",
      ].some(
        (key) =>
          typeof claims[key] !== "string" ||
          !OPAQUE_SEGMENT.test(claims[key] as string),
      )
    )
      return null;
    return { expiresAt: (claims.exp as number) * 1000 };
  } catch {
    return null;
  }
}
