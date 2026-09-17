/** Local transport deadline. A timeout does not prove that a server mutation failed. */
export class RequestDeadlineError extends Error {
  readonly code = "request_timeout";

  constructor() {
    super("The request exceeded its connection deadline.");
    this.name = "RequestDeadlineError";
  }
}

/**
 * Bounds headers and body consumption while preserving caller cancellation.
 * The callback must use the supplied child signal and must not replay a
 * mutation after an uncertain outcome.
 */
export async function withRequestDeadline<T>(
  parent: AbortSignal | null | undefined,
  timeoutMs: number,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  if (
    !Number.isSafeInteger(timeoutMs) ||
    timeoutMs < 1 ||
    timeoutMs > 2_147_483_647
  )
    throw new RangeError("Use a positive bounded request deadline.");
  if (parent?.aborted)
    throw parent.reason ?? new DOMException("Request cancelled.", "AbortError");

  const controller = new AbortController();
  let rejectAborted: (reason?: unknown) => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    rejectAborted = reject;
  });
  const childAborted = () =>
    rejectAborted(
      controller.signal.reason ??
        new DOMException("Request cancelled.", "AbortError"),
    );
  const parentAborted = () =>
    controller.abort(
      parent?.reason ?? new DOMException("Request cancelled.", "AbortError"),
    );
  controller.signal.addEventListener("abort", childAborted, { once: true });
  parent?.addEventListener("abort", parentAborted, { once: true });
  const timer = setTimeout(
    () => controller.abort(new RequestDeadlineError()),
    timeoutMs,
  );
  try {
    const work = Promise.resolve().then(() => {
      if (controller.signal.aborted) throw controller.signal.reason;
      return operation(controller.signal);
    });
    return await Promise.race([work, aborted]);
  } finally {
    clearTimeout(timer);
    parent?.removeEventListener("abort", parentAborted);
    controller.signal.removeEventListener("abort", childAborted);
  }
}
