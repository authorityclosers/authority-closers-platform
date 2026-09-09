import type {
  Loader,
  LoaderCallbacks,
  LoaderConfiguration,
  LoaderContext,
  LoaderStats,
  FragmentLoaderContext,
} from "hls.js";

const MANIFEST_LIMIT = 2 * 1024 * 1024;
const SEGMENT_LIMIT = 32 * 1024 * 1024;
const FIRST_BYTE_LIMIT_MS = 15_000;
const LOAD_LIMIT_MS = 60_000;
const PLAYLIST_TYPES = new Set([
  "manifest",
  "level",
  "audioTrack",
  "subtitleTrack",
]);
const PLAYLIST_MIMES = new Set([
  "application/vnd.apple.mpegurl",
  "application/x-mpegurl",
  "audio/mpegurl",
  "audio/x-mpegurl",
  "text/plain",
]);
const SEGMENT_MIMES = new Set([
  "video/mp2t",
  "video/mp4",
  "audio/mp4",
  "application/mp4",
]);
const safeMessage = "Authorized lesson media could not be loaded.";

function freshStats(): LoaderStats {
  return {
    aborted: false,
    loaded: 0,
    total: 0,
    retry: 0,
    chunkCount: 0,
    bwEstimate: 0,
    loading: { start: 0, first: 0, end: 0 },
    parsing: { start: 0, end: 0 },
    buffering: { start: 0, first: 0, end: 0 },
  };
}
function boundedTimeout(value: number | undefined, maximum: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.max(1, Math.min(value, maximum))
    : maximum;
}
function silent(callback: (() => void) | undefined) {
  try {
    callback?.();
  } catch {
    /* Never expose consumer/native diagnostics. */
  }
}

/** A single-use, non-retrying transport. HLS retains its required internal URL
 * context, but receives no native Response, error, statusText or diagnostic URL.
 * The caller owns authorization and must destroy the engine on scope expiry. */
export function createAuthorizedHlsLoader({
  allowedUrl,
  fetch: fetcher = (input, init) => globalThis.fetch(input, init),
  onDenied,
}: {
  allowedUrl: (url: string) => boolean;
  fetch?: typeof fetch;
  onDenied?: () => void;
}): new () => Loader<LoaderContext> {
  const permits = (value: string) => {
    try {
      const url = new URL(value);
      return (
        value.length <= 8192 &&
        url.href === value &&
        ["https:", "http:"].includes(url.protocol) &&
        !url.username &&
        !url.password &&
        !url.hash &&
        allowedUrl(value)
      );
    } catch {
      return false;
    }
  };
  return class AuthorizedHlsLoader implements Loader<LoaderContext> {
    public context: LoaderContext | null = null;
    // HLS assigns this object to fragment.stats before load(); retain its identity.
    public stats = freshStats();
    private callbacks: LoaderCallbacks<LoaderContext> | null = null;
    private controller: AbortController | null = null;
    private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    private firstTimer: ReturnType<typeof setTimeout> | undefined;
    private totalTimer: ReturnType<typeof setTimeout> | undefined;
    private used = false;
    private finished = false;
    private destroyed = false;

    load(
      context: LoaderContext,
      config: LoaderConfiguration,
      callbacks: LoaderCallbacks<LoaderContext>,
    ): void {
      if (this.used || this.destroyed || this.finished) {
        if (!this.destroyed && !this.finished)
          silent(() =>
            callbacks.onError(
              { code: 0, text: safeMessage },
              context,
              null,
              this.stats,
            ),
          );
        return;
      }
      this.used = true;
      this.context = context;
      this.callbacks = callbacks;
      this.controller = new AbortController();
      this.stats.loading.start = performance.now();
      const timeout = () => {
        if (this.finished) return;
        this.finished = true;
        this.stats.aborted = true;
        this.stats.loading.end = Math.max(
          performance.now(),
          this.stats.loading.start,
        );
        this.stop();
        silent(() => callbacks.onTimeout(this.stats, context, null));
      };
      this.firstTimer = setTimeout(
        timeout,
        boundedTimeout(
          config.loadPolicy?.maxTimeToFirstByteMs,
          FIRST_BYTE_LIMIT_MS,
        ),
      );
      this.totalTimer = setTimeout(
        timeout,
        boundedTimeout(config.loadPolicy?.maxLoadTimeMs, LOAD_LIMIT_MS),
      );
      void this.execute(context).catch(() => this.fail(0));
    }

    abort(): void {
      if (this.finished || this.destroyed) return;
      this.finished = true;
      this.stats.aborted = true;
      this.stats.loading.end = Math.max(
        performance.now(),
        this.stats.loading.start,
      );
      this.stop();
      const context = this.context;
      if (context)
        silent(() => this.callbacks?.onAbort?.(this.stats, context, null));
    }

    destroy(): void {
      this.destroyed = true;
      if (!this.finished) this.stats.aborted = true;
      this.finished = true;
      this.stop();
      this.callbacks = null;
      this.context = null;
    }

    private stop() {
      clearTimeout(this.firstTimer);
      clearTimeout(this.totalTimer);
      this.controller?.abort();
      void this.reader?.cancel().catch(() => undefined);
    }

    private fail(code: number, denied = false) {
      if (this.finished || this.destroyed) return;
      this.finished = true;
      this.stats.loading.end = Math.max(
        performance.now(),
        this.stats.loading.start,
      );
      this.stop();
      if (denied) silent(onDenied);
      const context = this.context;
      if (!this.destroyed && context)
        silent(() =>
          this.callbacks?.onError(
            { code, text: safeMessage },
            context,
            null,
            this.stats,
          ),
        );
    }

    private async execute(context: LoaderContext) {
      const source = context.url; // Snapshot before any asynchronous operation.
      if (!permits(source)) {
        this.fail(403, true);
        return;
      }
      const playlist =
        PLAYLIST_TYPES.has(context.type) && context.responseType === "text";
      const fragment =
        context.type === "media-fragment" &&
        context.responseType === "arraybuffer";
      if (!playlist && !fragment) {
        this.fail(0);
        return;
      }
      const subtitle =
        fragment &&
        (context as Partial<FragmentLoaderContext>).frag?.type === "subtitle";
      const limit = playlist || subtitle ? MANIFEST_LIMIT : SEGMENT_LIMIT;
      const headers = new Headers({
        accept: playlist
          ? "application/vnd.apple.mpegurl, application/x-mpegurl, text/plain"
          : subtitle
            ? "text/vtt"
            : "video/mp2t, video/mp4, audio/mp4, application/mp4",
      });
      // Only this loader's bounded byte range is forwarded, never context.headers.
      // Installed HLS emits 0/0 for ordinary fragments without a byte range.
      const noRange =
        (context.rangeStart === undefined && context.rangeEnd === undefined) ||
        (context.rangeStart === 0 && context.rangeEnd === 0);
      const hasRange = !noRange;
      let expectedRange: { start: number; end: number } | null = null;
      if (hasRange) {
        const start = context.rangeStart;
        const end = context.rangeEnd;
        if (
          playlist ||
          !Number.isSafeInteger(start) ||
          !Number.isSafeInteger(end) ||
          start! < 0 ||
          end! <= start! ||
          end! - start! > limit
        ) {
          this.fail(0);
          return;
        }
        expectedRange = { start: start!, end: end! };
        headers.set("range", `bytes=${start}-${end! - 1}`);
      }
      const response = await fetcher(source, {
        method: "GET",
        mode: "same-origin",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal: this.controller!.signal,
        headers,
      });
      if (this.finished || this.destroyed) {
        void response.body?.cancel().catch(() => undefined);
        return;
      }
      if (response.redirected || (response.url && response.url !== source)) {
        void response.body?.cancel().catch(() => undefined);
        this.fail(0);
        return;
      }
      if (!permits(source)) {
        void response.body?.cancel().catch(() => undefined);
        this.fail(403, true);
        return;
      }
      if (response.status !== (expectedRange ? 206 : 200)) {
        void response.body?.cancel().catch(() => undefined);
        this.fail(response.status, [401, 403, 410].includes(response.status));
        return;
      }
      const mime = (response.headers.get("content-type") ?? "")
        .split(";", 1)[0]
        .trim()
        .toLowerCase();
      const declared = response.headers.get("content-length");
      let expectedLength: number | null = null;
      if (declared !== null) {
        if (
          !/^(0|[1-9]\d*)$/.test(declared) ||
          !Number.isSafeInteger(Number(declared)) ||
          Number(declared) > limit
        ) {
          void response.body?.cancel().catch(() => undefined);
          this.fail(0);
          return;
        }
        expectedLength = Number(declared);
      }
      if (
        !(subtitle
          ? mime === "text/vtt"
          : (playlist ? PLAYLIST_MIMES : SEGMENT_MIMES).has(mime)) ||
        ![null, "identity"].includes(response.headers.get("content-encoding"))
      ) {
        void response.body?.cancel().catch(() => undefined);
        this.fail(0);
        return;
      }
      if (expectedRange) {
        const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(
          response.headers.get("content-range") ?? "",
        );
        if (
          !match ||
          Number(match[1]) !== expectedRange.start ||
          Number(match[2]) !== expectedRange.end - 1 ||
          !Number.isSafeInteger(Number(match[3])) ||
          Number(match[3]) < expectedRange.end ||
          (expectedLength !== null &&
            expectedLength !== expectedRange.end - expectedRange.start)
        ) {
          void response.body?.cancel().catch(() => undefined);
          this.fail(0);
          return;
        }
        expectedLength = expectedRange.end - expectedRange.start;
      }
      this.stats.total = expectedLength ?? 0;
      const reader = response.body?.getReader();
      if (!reader) {
        this.fail(0);
        return;
      }
      this.reader = reader;
      const chunks: Uint8Array[] = [];
      try {
        while (!this.finished) {
          const item = await reader.read();
          if (this.finished) return;
          if (item.done) break;
          if (!item.value.byteLength) continue;
          if (!this.stats.loading.first) {
            this.stats.loading.first = Math.max(
              performance.now(),
              this.stats.loading.start,
            );
            clearTimeout(this.firstTimer);
          }
          this.stats.loaded += item.value.byteLength;
          if (
            this.stats.loaded > limit ||
            (expectedLength !== null && this.stats.loaded > expectedLength)
          ) {
            this.fail(0);
            return;
          }
          chunks.push(item.value);
        }
      } finally {
        reader.releaseLock();
        if (this.reader === reader) this.reader = null;
      }
      if (this.finished) return;
      if (
        !this.stats.loaded ||
        (expectedLength !== null && this.stats.loaded !== expectedLength)
      ) {
        this.fail(0);
        return;
      }
      if (!permits(source)) {
        this.fail(403, true);
        return;
      }
      const bytes = new Uint8Array(this.stats.loaded);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      const data = playlist
        ? new TextDecoder("utf-8", { fatal: true }).decode(bytes)
        : bytes.buffer;
      if (
        typeof data === "string" &&
        !/^#EXTM3U(?:\r?\n|$)/.test(data.trimStart())
      ) {
        this.fail(0);
        return;
      }
      if (
        subtitle &&
        !/^WEBVTT(?:[ \t]|\r?\n|$)/.test(
          new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        )
      ) {
        this.fail(0);
        return;
      }
      this.stats.total = this.stats.loaded;
      this.stats.loading.end = Math.max(
        performance.now(),
        this.stats.loading.first,
      );
      this.stats.bwEstimate =
        (this.stats.loaded * 8000) /
        Math.max(1, this.stats.loading.end - this.stats.loading.first);
      this.finished = true;
      clearTimeout(this.firstTimer);
      clearTimeout(this.totalTimer);
      // XHR-style completed progress avoids feeding partial/unvalidated bytes.
      silent(() =>
        this.callbacks?.onProgress?.(this.stats, context, data, null),
      );
      if (!this.destroyed)
        silent(() =>
          this.callbacks?.onSuccess(
            { url: source, data, code: response.status },
            this.stats,
            context,
            null,
          ),
        );
    }
  };
}
