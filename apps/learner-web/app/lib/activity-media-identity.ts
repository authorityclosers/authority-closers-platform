import type { ActivityResponse } from "./learner-api";
import { isLocalSandboxMediaUrl } from "./local-sandbox";

const scopeKeys = [
  "tenant_id",
  "person_id",
  "session_id",
  "activity_id",
  "activity_version",
  "asset_id",
  "version_id",
  "binding_id",
  "enrollment_id",
] as const;
const claimKeys = [
  ...scopeKeys,
  "delivery_grant_id",
  "typ",
  "token_type",
  "key",
  "supports_range",
  "iat",
  "exp",
  "nonce",
].sort();
const identifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
type Claims = Record<(typeof scopeKeys)[number], string> & {
  delivery_grant_id: string;
  typ: "AC-MEDIA";
  token_type: "playback";
  key: string;
  supports_range: boolean;
  iat: number;
  exp: number;
  nonce: string;
};
type Envelope = { origin: string; path: string; claims: Claims };
type MediaSource = {
  protocol?: string;
  src: string;
  fallback?: { src: string };
};
export type ActivityMediaIdentity = {
  identity: string;
  expiresAt: number;
  issuedAt: number;
  grantId: string;
};

function base64Url(binary: string): string {
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Structural comparison only: the authenticated byte service verifies signatures. */
function envelope(source: string): Envelope | null {
  if (typeof source !== "string" || source.length > 8192) return null;
  try {
    const url = new URL(source);
    if (
      url.href !== source ||
      url.username ||
      url.password ||
      url.hash ||
      (url.protocol !== "https:" && !isLocalSandboxMediaUrl(url)) ||
      !url.pathname.startsWith("/v1/media/playback/") ||
      !/^\?token=AC-MEDIA\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(url.search)
    )
      return null;
    const token = url.searchParams.get("token")!;
    if (token.length > 4096) return null;
    const [, encoded, signature] = token.split(".");
    const decode = (value: string) =>
      atob(
        value
          .replace(/-/g, "+")
          .replace(/_/g, "/")
          .padEnd(Math.ceil(value.length / 4) * 4, "="),
      );
    const binary = decode(encoded);
    if (
      base64Url(binary) !== encoded ||
      base64Url(decode(signature)) !== signature
    )
      return null;
    const json = new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(binary, (c) => c.charCodeAt(0)),
    );
    const value: unknown = JSON.parse(json);
    if (!value || typeof value !== "object" || Array.isArray(value))
      return null;
    const claims = value as Record<string, unknown>;
    const keys = Object.keys(claims).sort();
    // The signer emits sorted, compact JSON. Besides bounding the accepted
    // contract, this rejects duplicate keys and ambiguous JSON representations.
    if (
      keys.join("|") !== claimKeys.join("|") ||
      json !==
        JSON.stringify(
          Object.fromEntries(keys.map((key) => [key, claims[key]])),
        ) ||
      claims.typ !== "AC-MEDIA" ||
      claims.token_type !== "playback" ||
      [...scopeKeys, "delivery_grant_id"].some(
        (key) =>
          typeof claims[key] !== "string" ||
          !identifier.test(claims[key] as string),
      ) ||
      typeof claims.supports_range !== "boolean" ||
      typeof claims.nonce !== "string" ||
      !/^[A-Za-z0-9_-]{1,128}$/.test(claims.nonce) ||
      !Number.isSafeInteger(claims.iat) ||
      !Number.isSafeInteger(claims.exp) ||
      (claims.iat as number) < 0 ||
      (claims.exp as number) <= (claims.iat as number) ||
      (claims.exp as number) - (claims.iat as number) > 3600 ||
      !Number.isSafeInteger((claims.exp as number) * 1000)
    )
      return null;
    const encodedKey = url.pathname.slice("/v1/media/playback/".length);
    const key = decodeURIComponent(encodedKey);
    const parts = key.split("/");
    if (
      key.length > 512 ||
      key.includes("..") ||
      key !== claims.key ||
      encodeURIComponent(key) !== encodedKey ||
      parts.length < 8 ||
      parts[0] !== "tenants" ||
      parts[1] !== claims.tenant_id ||
      parts[2] !== "media" ||
      parts[3] !== "video" ||
      parts[4] !== claims.asset_id ||
      parts[5] !== claims.version_id ||
      parts[6] !== "original" ||
      parts.some((part) => !identifier.test(part))
    )
      return null;
    return { origin: url.origin, path: url.pathname, claims: claims as Claims };
  } catch {
    return null;
  }
}

function sameGeneration(primary: Envelope, other: Envelope): boolean {
  return (
    primary.origin === other.origin &&
    [...scopeKeys, "delivery_grant_id", "iat", "exp"].every(
      (key) =>
        primary.claims[key as keyof Claims] ===
        other.claims[key as keyof Claims],
    )
  );
}

function objectIdentity(value: Envelope) {
  return [
    value.origin,
    value.path,
    value.claims.token_type,
    value.claims.supports_range,
  ];
}

function positiveNumberOrNull(value: unknown): boolean {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value > 0)
  );
}

/**
 * Recognizes a complete application delivery descriptor for rotation comparison.
 * Never authorizes playback, verifies a signature, or extends a grant. There is
 * deliberately no current-time check: an expired original may be compared with
 * a separately authorized fresh descriptor. Callers still enforce fresh expiry.
 *
 * Null retains the caller's exact-source legacy comparison; it must not be
 * treated as a shared identity for two unrecognized or malformed sources.
 */
export function activityMediaIdentity(
  activity: ActivityResponse,
  media: MediaSource | null,
  mode: string,
): ActivityMediaIdentity | null {
  const descriptor = activity.media;
  if (
    !media ||
    !descriptor ||
    descriptor.state !== "approved" ||
    descriptor.playback_available !== true ||
    typeof activity.kind !== "string" ||
    activity.kind.toLowerCase() !== "video" ||
    typeof activity.state !== "string" ||
    !["available", "in_progress"].includes(activity.state.toLowerCase()) ||
    !["tracked", "read-only"].includes(mode) ||
    ![
      activity.id,
      activity.program_id,
      activity.program_version_id,
      activity.enrollment_id,
      descriptor.binding_id,
      descriptor.media_id,
      descriptor.media_version_id,
      descriptor.activity_version,
    ].every((value) => typeof value === "string" && identifier.test(value)) ||
    !positiveNumberOrNull(descriptor.duration_seconds) ||
    !positiveNumberOrNull(descriptor.width) ||
    !positiveNumberOrNull(descriptor.height) ||
    typeof descriptor.content_type !== "string" ||
    !/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/.test(descriptor.content_type) ||
    !Array.isArray(descriptor.captions) ||
    descriptor.captions.length > 100 ||
    !Array.isArray(descriptor.renditions) ||
    descriptor.renditions.length > 100 ||
    !descriptor.delivery ||
    !["hls", "progressive"].includes(descriptor.delivery.protocol)
  )
    return null;
  const primary = envelope(media.src);
  if (
    !primary ||
    primary.claims.activity_id !== activity.id ||
    primary.claims.activity_version !== descriptor.activity_version ||
    primary.claims.asset_id !== descriptor.media_id ||
    primary.claims.version_id !== descriptor.media_version_id ||
    primary.claims.binding_id !== descriptor.binding_id ||
    primary.claims.enrollment_id !== activity.enrollment_id
  )
    return null;
  const protocol = media.protocol ?? "progressive";
  const { manifest_url: manifest, progressive_url: progressive } =
    descriptor.delivery;
  if (
    (protocol !== "hls" && protocol !== "progressive") ||
    (protocol === "hls" &&
      (descriptor.delivery.protocol !== "hls" || media.src !== manifest)) ||
    (protocol === "progressive" && media.src !== progressive) ||
    (media.fallback &&
      (protocol !== "hls" || media.fallback.src !== progressive))
  )
    return null;
  const sources: unknown[] = [];
  for (const source of [manifest, progressive]) {
    if (source === null) {
      sources.push(null);
      continue;
    }
    const resolved = typeof source === "string" ? envelope(source) : null;
    if (!resolved || !sameGeneration(primary, resolved)) return null;
    sources.push(objectIdentity(resolved));
  }
  const captions: unknown[] = [];
  const captionIds = new Set<string>();
  for (const caption of descriptor.captions) {
    if (
      !caption ||
      typeof caption.id !== "string" ||
      !identifier.test(caption.id) ||
      captionIds.has(caption.id) ||
      caption.media_version_id !== descriptor.media_version_id ||
      !["captions", "subtitles", "transcript"].includes(caption.kind) ||
      !["ready", "superseded", "retired"].includes(caption.state) ||
      typeof caption.language !== "string" ||
      !/^[A-Za-z0-9-]{1,64}$/.test(caption.language) ||
      typeof caption.is_default !== "boolean" ||
      caption.content_type !== "text/vtt" ||
      typeof caption.created_at !== "string" ||
      caption.created_at.length > 64 ||
      !Number.isFinite(Date.parse(caption.created_at)) ||
      (caption.supersedes_caption_id != null &&
        (typeof caption.supersedes_caption_id !== "string" ||
          !identifier.test(caption.supersedes_caption_id)))
    )
      return null;
    captionIds.add(caption.id);
    const source = caption.source_url;
    const resolved = typeof source === "string" ? envelope(source) : null;
    if (source != null && (!resolved || !sameGeneration(primary, resolved)))
      return null;
    if (caption.state === "ready" && !resolved) return null;
    captions.push([
      caption.id,
      caption.media_version_id,
      caption.language,
      caption.kind,
      caption.state,
      caption.content_type,
      caption.is_default,
      caption.created_at,
      caption.supersedes_caption_id ?? null,
      resolved ? objectIdentity(resolved) : null,
    ]);
  }
  const renditionIds = new Set<string>();
  const renditions: unknown[] = [];
  for (const rendition of descriptor.renditions) {
    if (
      !rendition ||
      typeof rendition.id !== "string" ||
      !identifier.test(rendition.id) ||
      renditionIds.has(rendition.id) ||
      !["hls", "progressive"].includes(rendition.protocol) ||
      typeof rendition.content_type !== "string" ||
      !/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/.test(rendition.content_type) ||
      !positiveNumberOrNull(rendition.width) ||
      !positiveNumberOrNull(rendition.height) ||
      !positiveNumberOrNull(rendition.bitrate_kbps)
    )
      return null;
    renditionIds.add(rendition.id);
    renditions.push([
      rendition.id,
      rendition.protocol,
      rendition.content_type,
      rendition.width,
      rendition.height,
      rendition.bitrate_kbps,
    ]);
  }
  return {
    identity: JSON.stringify([
      "ac-activity-media-v1",
      scopeKeys.map((key) => primary.claims[key]),
      activity.program_id,
      activity.program_version_id,
      mode,
      protocol,
      Boolean(media.fallback),
      descriptor.delivery.protocol,
      descriptor.content_type,
      descriptor.duration_seconds,
      descriptor.width,
      descriptor.height,
      sources,
      captions,
      renditions,
    ]),
    expiresAt: primary.claims.exp * 1000,
    issuedAt: primary.claims.iat * 1000,
    grantId: primary.claims.delivery_grant_id,
  };
}
