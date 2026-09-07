"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEVELOPMENT_MEDIA_MAX_SOURCES,
  developmentMediaRegistrationUrl,
  isDevelopmentMediaLocatorPath,
  readDevelopmentMediaSource,
} from "../lib/dev-media-transport";

const DevelopmentMediaOrigin = createContext<string | null>(null);

export function DevelopmentMediaBridgeProvider({
  browserOrigin,
  children,
}: {
  browserOrigin: string | null;
  children: ReactNode;
}) {
  return (
    <DevelopmentMediaOrigin.Provider value={browserOrigin}>
      {children}
    </DevelopmentMediaOrigin.Provider>
  );
}

type TransportState = {
  scope: string;
  status: "ready" | "failed";
  items: Map<string, { url: string; expiresAt: number }>;
};

export function useDevelopmentMediaTransport(
  approvedSources: readonly string[] = [],
): {
  enabled: boolean;
  pending: boolean;
  refresh: () => void;
  resolveUrl: (approvedHttpsSource: string) => string | null;
} {
  const browserOrigin = useContext(DevelopmentMediaOrigin);
  const enabled =
    process.env.NODE_ENV === "development" && browserOrigin !== null;
  const [registrationEpoch, setRegistrationEpoch] = useState(0);
  const refresh = useCallback(() => {
    if (enabled) setRegistrationEpoch((epoch) => epoch + 1);
  }, [enabled]);
  const registrationUrl = enabled
    ? developmentMediaRegistrationUrl(
        browserOrigin!,
        typeof window === "undefined" ? null : window.location.origin,
      )
    : null;
  // Descriptors and keys remain memory-only. Signed sources never enter local
  // request URLs, browser storage, errors, or registration responses.
  const scope = JSON.stringify([
    registrationUrl,
    [...new Set(approvedSources)],
    registrationEpoch,
  ]);
  const eligible =
    approvedSources.length > 0 &&
    new Set(approvedSources).size <= DEVELOPMENT_MEDIA_MAX_SOURCES &&
    approvedSources.every(
      (source) => readDevelopmentMediaSource(source) !== null,
    );
  const [state, setState] = useState<TransportState | null>(null);
  useEffect(() => {
    if (!enabled || !registrationUrl || !eligible) return;
    const [, sources] = JSON.parse(scope) as [string, string[]];
    if (
      sources.length < 1 ||
      sources.length > DEVELOPMENT_MEDIA_MAX_SOURCES ||
      sources.some((source) => !readDevelopmentMediaSource(source))
    )
      return;
    const controller = new AbortController();
    let current = true;
    let expirationTimer: ReturnType<typeof setTimeout> | undefined;
    const fail = () => {
      if (current) setState({ scope, status: "failed", items: new Map() });
    };
    const timeout = setTimeout(() => {
      controller.abort();
      fail();
    }, 12_000);
    void (async () => {
      try {
        const response = await fetch(registrationUrl, {
          method: "POST",
          mode: "same-origin",
          credentials: "same-origin",
          redirect: "error",
          cache: "no-store",
          signal: controller.signal,
          headers: {
            "content-type": "application/json",
            accept: "application/json",
          },
          body: JSON.stringify({ sources }),
        });
        if (
          !response.ok ||
          !/^application\/json(?:;|$)/i.test(
            response.headers.get("content-type") ?? "",
          )
        ) {
          void response.body?.cancel().catch(() => undefined);
          throw new Error("Registration unavailable");
        }
        const reader = response.body?.getReader();
        if (!reader) throw new Error("Registration unavailable");
        const cancelRead = () => {
          void reader.cancel().catch(() => undefined);
        };
        controller.signal.addEventListener("abort", cancelRead, { once: true });
        let total = 0;
        const chunks: Uint8Array[] = [];
        try {
          while (true) {
            if (controller.signal.aborted)
              throw new Error("Registration unavailable");
            const { done, value } = await reader.read();
            if (done) break;
            total += value.byteLength;
            if (total > 16_384) {
              cancelRead();
              throw new Error("Registration unavailable");
            }
            chunks.push(value);
          }
        } finally {
          controller.signal.removeEventListener("abort", cancelRead);
          reader.releaseLock();
        }
        const bytes = new Uint8Array(total);
        let offset = 0;
        for (const chunk of chunks) {
          bytes.set(chunk, offset);
          offset += chunk.byteLength;
        }
        const payload: unknown = JSON.parse(
          new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        );
        if (
          !payload ||
          typeof payload !== "object" ||
          Array.isArray(payload) ||
          !("items" in payload) ||
          !Array.isArray(payload.items) ||
          payload.items.length !== sources.length
        )
          throw new Error("Registration unavailable");
        const items = new Map<string, { url: string; expiresAt: number }>();
        for (const [index, item] of payload.items.entries()) {
          const approval = readDevelopmentMediaSource(sources[index]);
          if (
            !approval ||
            !item ||
            typeof item !== "object" ||
            typeof item.path !== "string" ||
            !isDevelopmentMediaLocatorPath(item.path) ||
            !Number.isSafeInteger(item.expires_at) ||
            item.expires_at <= Date.now() ||
            item.expires_at > approval.expiresAt
          )
            throw new Error("Registration unavailable");
          items.set(sources[index], {
            url: new URL(item.path, registrationUrl).href,
            expiresAt: item.expires_at,
          });
        }
        if (!current || controller.signal.aborted) return;
        clearTimeout(timeout);
        setState({ scope, status: "ready", items });
        expirationTimer = setTimeout(
          fail,
          Math.max(
            0,
            Math.min(...[...items.values()].map((item) => item.expiresAt)) -
              Date.now(),
          ),
        );
      } catch {
        controller.abort();
        fail();
      } finally {
        clearTimeout(timeout);
      }
    })();
    return () => {
      current = false;
      controller.abort();
      clearTimeout(timeout);
      clearTimeout(expirationTimer);
    };
  }, [enabled, registrationUrl, scope, eligible]);
  return useMemo(
    () => ({
      enabled,
      refresh,
      pending:
        enabled &&
        registrationUrl !== null &&
        eligible &&
        state?.scope !== scope,
      resolveUrl: (source: string) => {
        if (!enabled) return source;
        if (
          !registrationUrl ||
          state?.scope !== scope ||
          state.status !== "ready"
        )
          return null;
        const item = state.items.get(source);
        return item &&
          item.expiresAt > Date.now() &&
          readDevelopmentMediaSource(source)
          ? item.url
          : null;
      },
    }),
    [enabled, registrationUrl, eligible, state, scope, refresh],
  );
}
