/**
 * The Android app as published right now: the sales-xray-apps repo's latest
 * normal release (owner, 18 Oct: "extremely easy to download and install").
 * The page reads it on the server at most every 10 minutes, so the version,
 * size and SHA-256 never go stale; if GitHub can't be reached the download
 * still works, only the details are left out.
 */

export const APPS_REPO = "authorityclosers/sales-xray-apps";
/** Always the newest normal release's APK (GitHub follows "latest" itself). */
export const ANDROID_APK_URL = `https://github.com/${APPS_REPO}/releases/latest/download/sales-xray-android.apk`;
const LATEST_API = `https://api.github.com/repos/${APPS_REPO}/releases/latest`;
const APK = "sales-xray-android.apk";

export type AndroidRelease = {
  url: string;
  version: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  updatedAt: string | null;
};

export const UNKNOWN_RELEASE: AndroidRelease = {
  url: ANDROID_APK_URL,
  version: null,
  sizeBytes: null,
  sha256: null,
  updatedAt: null,
};

type Asset = {
  name?: unknown;
  size?: unknown;
  digest?: unknown;
  updated_at?: unknown;
};

/** GitHub's release JSON -> what the page shows. Anything odd is simply left out. */
export function readRelease(body: unknown): AndroidRelease {
  if (!body || typeof body !== "object") return UNKNOWN_RELEASE;
  const release = body as { name?: unknown; assets?: unknown };
  const assets = Array.isArray(release.assets)
    ? (release.assets as Asset[])
    : [];
  const apk = assets.find((asset) => asset?.name === APK);
  if (!apk) return UNKNOWN_RELEASE;
  const name = typeof release.name === "string" ? release.name : "";
  const version = /(\d+\.\d+\.\d+)/.exec(name)?.[1] ?? null;
  const digest =
    typeof apk.digest === "string"
      ? /^sha256:([0-9a-f]{64})$/.exec(apk.digest)
      : null;
  const size =
    typeof apk.size === "number" && Number.isFinite(apk.size) && apk.size > 0
      ? apk.size
      : null;
  const updated =
    typeof apk.updated_at === "string" &&
    !Number.isNaN(Date.parse(apk.updated_at))
      ? apk.updated_at
      : null;
  return {
    url: ANDROID_APK_URL,
    version,
    sizeBytes: size,
    sha256: digest ? digest[1] : null,
    updatedAt: updated,
  };
}

/** "4.1 MB" (decimal megabytes, as phones show download sizes). */
export function formatSize(bytes: number | null): string | null {
  if (bytes === null) return null;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export async function latestAndroidRelease(
  load: typeof fetch = fetch,
): Promise<AndroidRelease> {
  try {
    const response = await load(LATEST_API, {
      headers: { accept: "application/vnd.github+json" },
      next: { revalidate: 600 },
      signal: AbortSignal.timeout(4000),
    } as RequestInit);
    if (!response.ok) return UNKNOWN_RELEASE;
    return readRelease(await response.json());
  } catch {
    return UNKNOWN_RELEASE;
  }
}
