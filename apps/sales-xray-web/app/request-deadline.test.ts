import { afterEach, describe, expect, it, vi } from "vitest";
import { RequestDeadlineError, withRequestDeadline } from "./request-deadline";

afterEach(() => vi.useRealTimers());

describe("withRequestDeadline", () => {
  it("returns a completed operation and removes its timer", async () => {
    vi.useFakeTimers();
    await expect(
      withRequestDeadline(undefined, 100, async () => "complete"),
    ).resolves.toBe("complete");
    await vi.advanceTimersByTimeAsync(100);
  });

  it("aborts the child operation when headers or body never complete", async () => {
    vi.useFakeTimers();
    let child: AbortSignal | undefined;
    const pending = withRequestDeadline(undefined, 25, async (signal) => {
      child = signal;
      return new Promise<never>(() => {});
    });
    const assertion =
      expect(pending).rejects.toBeInstanceOf(RequestDeadlineError);
    await vi.advanceTimersByTimeAsync(25);
    await assertion;
    expect(child?.aborted).toBe(true);
  });

  it("preserves parent cancellation instead of converting it to a timeout", async () => {
    const parent = new AbortController();
    const pending = withRequestDeadline(parent.signal, 1000, async (signal) => {
      await new Promise<void>((resolve) =>
        signal.addEventListener("abort", () => resolve(), { once: true }),
      );
      throw signal.reason;
    });
    parent.abort("caller_cancelled");
    await expect(pending).rejects.toBe("caller_cancelled");
  });

  it("rejects invalid deadlines before dispatching the operation", async () => {
    const operation = vi.fn(async () => "never");
    await expect(withRequestDeadline(undefined, 0, operation)).rejects.toThrow(
      "positive bounded request deadline",
    );
    expect(operation).not.toHaveBeenCalled();
  });
});
