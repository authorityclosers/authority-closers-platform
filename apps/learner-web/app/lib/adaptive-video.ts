import type Hls from "hls.js";
import { createAuthorizedHlsLoader } from "./authorized-hls-loader";
import { isLocalSandboxMediaUrl } from "./local-sandbox";

export type AdaptiveQuality = { id: string; label: string };
export type AdaptiveMode = "hls" | "native-hls" | "progressive";
export type AdaptiveVideo = {
  selectQuality: (id: string) => boolean;
  destroy: () => void;
  ready: Promise<void>;
};
type HlsModule = typeof import("hls.js");
type Options = {
  video: HTMLVideoElement;
  manifestUrl: string;
  fallbackUrl?: string;
  onMode: (mode: AdaptiveMode) => void;
  onQualities: (qualities: AdaptiveQuality[]) => void;
  onQuality: (id: string) => void;
  onError: () => void;
  onDenied: () => void;
};

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
  "delivery_grant_id",
] as const;
/** Withholding-only checks, never signature verification or authorization. */
function deliveryScope(value: string, now: number) {
  if (value.length > 8192) return null;
  try {
    const url = new URL(value);
    if (
      url.href !== value ||
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
    const encoded = token.split(".")[1];
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
        Uint8Array.from(binary, (c) => c.charCodeAt(0)),
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
      (claims.iat as number) * 1000 > now + 30_000 ||
      (claims.exp as number) <= (claims.iat as number) ||
      (claims.exp as number) - (claims.iat as number) > 3600 ||
      !Number.isSafeInteger((claims.exp as number) * 1000) ||
      (claims.exp as number) * 1000 <= now ||
      scopeKeys.some(
        (key) =>
          typeof claims[key] !== "string" ||
          !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(claims[key] as string),
      )
    )
      return null;
    const key = decodeURIComponent(
      url.pathname.slice("/v1/media/playback/".length),
    );
    const parts = key.split("/");
    if (
      key.length > 512 ||
      key.includes("..") ||
      !key.startsWith("tenants/") ||
      key !== claims.key ||
      encodeURIComponent(key) !==
        url.pathname.slice("/v1/media/playback/".length) ||
      parts.length < 7 ||
      parts[1] !== claims.tenant_id ||
      parts[2] !== "media" ||
      parts[3] !== "video" ||
      parts[4] !== claims.asset_id ||
      parts[5] !== claims.version_id ||
      parts.some((part) => !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(part))
    )
      return null;
    return { url, claims };
  } catch {
    return null;
  }
}

/** Children must retain the original server-issued grant, identity and lifetime. */
export function authorizedHlsRequestPredicate(
  manifestUrl: string,
  clock = Date.now,
) {
  const master = deliveryScope(manifestUrl, clock());
  return (candidate: string) => {
    const child = deliveryScope(candidate, clock());
    return Boolean(
      master &&
        child &&
        master.url.origin === child.url.origin &&
        [...scopeKeys, "iat", "exp"].every(
          (key) => master.claims[key] === child.claims[key],
        ),
    );
  };
}

/** Owns only decoding/delivery. The containing viewer still owns evidence and grants. */
export function attachAdaptiveVideo(
  options: Options,
  load: () => Promise<HlsModule> = () => import("hls.js"),
): AdaptiveVideo {
  const { video } = options;
  const allowedUrl = authorizedHlsRequestPredicate(options.manifestUrl);
  let disposed = false;
  let engine: Hls | null = null;
  let qualityIds: string[] = [];
  const clear = () => {
    const current = engine;
    engine = null;
    current?.destroy();
    video.pause();
    video.removeAttribute("src");
    video.load();
  };
  const destroy = () => {
    if (disposed) return;
    disposed = true;
    clear();
  };
  const denied = () => {
    if (disposed) return;
    destroy();
    options.onDenied();
  };
  const error = () => {
    if (disposed) return;
    disposed = true;
    // Let the viewer retain its presentation cursor before load() clears it.
    // Recovery still requires a fresh authorization check and a new adapter.
    try {
      options.onError();
    } finally {
      clear();
    }
  };
  const ready = (async () => {
    if (!allowedUrl(options.manifestUrl)) {
      denied();
      return;
    }
    try {
      const { default: HlsClass, Events } = await load();
      if (disposed) return;
      // This adapter handles the application's signed same-origin delivery only.
      if (new URL(options.manifestUrl).origin !== window.location.origin) {
        denied();
        return;
      }
      if (!HlsClass.isSupported()) {
        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          options.onMode("native-hls");
          video.src = options.manifestUrl;
          video.load();
        } else if (options.fallbackUrl && allowedUrl(options.fallbackUrl)) {
          options.onMode("progressive");
          video.src = options.fallbackUrl;
          video.load();
        } else error();
        return;
      }
      const Loader = createAuthorizedHlsLoader({
        allowedUrl,
        onDenied: denied,
      });
      engine = new HlsClass({
        debug: false,
        loader: Loader,
        enableWorker: true,
        lowLatencyMode: false,
        // The viewer already owns authorized <track> captions and their controls.
        renderTextTracksNatively: false,
        capLevelToPlayerSize: true,
        backBufferLength: 20,
        maxBufferLength: 20,
        maxMaxBufferLength: 30,
        maxBufferSize: 32 * 1024 * 1024,
        manifestLoadPolicy: {
          default: {
            maxTimeToFirstByteMs: 8000,
            maxLoadTimeMs: 12000,
            timeoutRetry: null,
            errorRetry: null,
          },
        },
        playlistLoadPolicy: {
          default: {
            maxTimeToFirstByteMs: 8000,
            maxLoadTimeMs: 12000,
            timeoutRetry: null,
            errorRetry: null,
          },
        },
        fragLoadPolicy: {
          default: {
            maxTimeToFirstByteMs: 8000,
            maxLoadTimeMs: 20000,
            timeoutRetry: null,
            errorRetry: null,
          },
        },
      });
      const current = engine;
      current.on(Events.MANIFEST_PARSED, () => {
        if (disposed || engine !== current) return;
        if (!current.levels.length || current.levels.length > 16) {
          error();
          return;
        }
        const qualities = current.levels.flatMap((level, index) =>
          Number.isInteger(level.height) &&
          level.height > 0 &&
          level.height <= 8640
            ? [{ id: `hls-${index}`, label: `${level.height}p` }]
            : [],
        );
        qualityIds = qualities.map((item) => item.id);
        options.onQualities(qualities);
      });
      current.on(Events.LEVEL_SWITCHED, (_event, data) => {
        const id = `hls-${data.level}`;
        if (
          !disposed &&
          engine === current &&
          Number.isInteger(data.level) &&
          qualityIds.includes(id)
        )
          options.onQuality(id);
      });
      current.on(Events.ERROR, (_event, data) => {
        if (disposed || engine !== current) return;
        if ([401, 403, 410].includes(data.response?.code ?? 0)) denied();
        else if (data.fatal) error();
      });
      options.onMode("hls");
      current.attachMedia(video);
      current.loadSource(options.manifestUrl);
    } catch {
      if (!disposed) error();
    }
  })();
  return {
    ready,
    destroy,
    selectQuality(id) {
      if (disposed || !engine || (id !== "auto" && !qualityIds.includes(id)))
        return false;
      // Hls flushes/reloads the selected level without replacing the media element.
      engine.currentLevel = id === "auto" ? -1 : Number(id.slice(4));
      return true;
    },
  };
}
