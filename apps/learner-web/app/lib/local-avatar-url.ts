import { LOCAL_SANDBOX_ORIGIN } from "./local-sandbox";

export const LOCAL_AVATAR_UPLOAD_PREFIX = "/v1/media/local-avatar-upload/";
export const LOCAL_AVATAR_READ_PREFIX = "/v1/media/read/";
export const MAX_LOCAL_AVATAR_BYTES = 5 * 1024 * 1024;
const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const original = `tenants/${uuid}/media/avatar/${uuid}/${uuid}/original`;

/** URL structure is a transport hint, never an upload/read authorization. */
export function isLocalAvatarObjectUrl(
  url: URL,
  operation: "upload" | "read",
): boolean {
  const prefix =
    operation === "upload"
      ? LOCAL_AVATAR_UPLOAD_PREFIX
      : LOCAL_AVATAR_READ_PREFIX;
  let key: string;
  try {
    key = decodeURIComponent(url.pathname.slice(prefix.length));
  } catch {
    return false;
  }
  return (
    url.pathname.startsWith(prefix) &&
    !url.username &&
    !url.password &&
    !url.hash &&
    new RegExp(
      `^${original}${operation === "read" ? "/avatar/(?:128|256|512)" : ""}$`,
    ).test(key) &&
    encodeURIComponent(key) === url.pathname.slice(prefix.length) &&
    /^\?token=AC-MEDIA\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(url.search) &&
    url.search.length <= 4103
  );
}

export function isLocalSandboxAvatarUploadUrl(
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
    isLocalAvatarObjectUrl(url, "upload")
  );
}
