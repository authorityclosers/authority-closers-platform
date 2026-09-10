import type { PracticeEngineApi } from "./practice-engine-api";

type AvailabilityFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

/** No local/persisted grants: hide navigation unless both runtime and current API admit it. */
export async function loadPracticeNavigationAvailability(
  signal: AbortSignal,
  fetcher: AvailabilityFetch = (input, init) => globalThis.fetch(input, init),
  api?: Pick<PracticeEngineApi, "profile">,
): Promise<boolean> {
  const controller = new AbortController();
  let cancel: (() => void) | undefined;
  const cancelled = new Promise<false>((resolve) => {
    cancel = () => resolve(false);
  });
  const abort = () => {
    controller.abort();
    cancel?.();
  };
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, 6_000);
  const check = async () => {
    if (controller.signal.aborted) return false;
    const response = await fetcher("/practice/availability", {
      method: "GET",
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    const length = response.headers.get("content-length");
    if (
      controller.signal.aborted ||
      !response.ok ||
      response.redirected ||
      !/^application\/json(?:\s*;|$)/i.test(
        response.headers.get("content-type") ?? "",
      ) ||
      (length !== null && (!/^\d+$/.test(length) || Number(length) > 1024))
    ) {
      void response.body?.cancel().catch(() => undefined);
      return false;
    }
    const reader = response.body?.getReader();
    if (!reader) return false;
    const stop = () => {
      void reader.cancel().catch(() => undefined);
    };
    controller.signal.addEventListener("abort", stop, { once: true });
    let size = 0;
    const parts: Uint8Array[] = [];
    try {
      while (!controller.signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 1024) {
          stop();
          return false;
        }
        parts.push(value);
      }
    } finally {
      controller.signal.removeEventListener("abort", stop);
      reader.releaseLock();
    }
    if (controller.signal.aborted) return false;
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.byteLength;
    }
    const result: unknown = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    );
    if (
      !result ||
      typeof result !== "object" ||
      Array.isArray(result) ||
      Object.keys(result).length !== 1 ||
      !("enabled" in result) ||
      result.enabled !== true
    )
      return false;
    // This is the existing read-only self profile, not a new capability claim.
    // Keep the disabled pilot's client/schema bundle out of the shared shell.
    const admittedApi =
      api ?? (await import("./practice-engine-api")).practiceEngineApi;
    if (controller.signal.aborted) return false;
    await admittedApi.profile(controller.signal);
    return !controller.signal.aborted;
  };
  try {
    return await Promise.race([check(), cancelled]);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
