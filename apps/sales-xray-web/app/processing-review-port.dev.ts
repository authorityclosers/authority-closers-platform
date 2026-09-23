"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { parseProgress, parseSubmission, UUID } from "./acquisition-client";
import type { ProcessingReview } from "./processing-review-port";

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  window.addEventListener("popstate", listener);
  return () => {
    window.removeEventListener("hashchange", listener);
    window.removeEventListener("popstate", listener);
  };
}
export function reviewFrameId(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  if (
    params.get("sx-review") !== "v1" ||
    params.get("mode") !== "observed" ||
    params.getAll("frame").length !== 1 ||
    [...params.keys()].some(
      (key) => !["sx-review", "mode", "frame"].includes(key),
    ) ||
    params.getAll("sx-review").length !== 1 ||
    params.getAll("mode").length !== 1
  )
    return null;
  const id = params.get("frame");
  return id && UUID.test(id) ? id : null;
}
export function useProcessingReview(callId: string | null): ProcessingReview {
  const hash = useSyncExternalStore(
    subscribe,
    () => window.location.hash,
    () => "",
  );
  const requested = hash.startsWith("#sx-review=");
  const id = reviewFrameId(hash);
  const [value, setValue] = useState<{
    key: string;
    frame: ProcessingReview["frame"];
    message: string;
  }>({ key: "", frame: null, message: "" });
  const key = callId + ":" + id;
  useEffect(() => {
    if (!requested || !callId || !id) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const response = await fetch(`/__review/api/frames/${id}`, {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal: abort.signal,
        });
        if (!response.ok)
          throw Error(
            "This state was not captured, expired, or is no longer accessible. Return to the controls and verify the call again.",
          );
        const body: unknown = await response.json();
        if (
          !body ||
          typeof body !== "object" ||
          !("receipt" in body) ||
          !("leaseUntil" in body) ||
          !("observedAt" in body)
        )
          throw Error("The observed state could not be verified.");
        const submission = parseSubmission(body.receipt),
          progress = parseProgress(body.receipt, submission);
        if (
          submission.id !== callId ||
          progress.has_report ||
          !progress.automatic_progression ||
          typeof body.leaseUntil !== "number" ||
          typeof body.observedAt !== "number" ||
          body.leaseUntil <= Date.now() ||
          body.leaseUntil > Date.now() + 31_000
        )
          throw Error(
            "This observation cannot be reopened as a processing screen. Open the live call instead.",
          );
        if (abort.signal.aborted) return;
        setValue({
          key,
          frame: { submission, progress, observedAt: body.observedAt },
          message: "",
        });
        if (expiry) clearTimeout(expiry);
        expiry = setTimeout(
          () =>
            setValue({
              key,
              frame: null,
              message:
                "Live access verification expired. Reopen the controls to verify access.",
            }),
          Math.max(0, body.leaseUntil - Date.now()),
        );
        timer = setTimeout(() => void refresh(), 15_000);
      } catch (error) {
        if (!abort.signal.aborted)
          setValue({
            key,
            frame: null,
            message:
              error instanceof Error
                ? error.message
                : "Live access verification failed.",
          });
      }
    }
    void refresh();
    return () => {
      abort.abort();
      if (timer) clearTimeout(timer);
      if (expiry) clearTimeout(expiry);
    };
  }, [requested, callId, id, key]);
  return {
    requested,
    frame: requested && value.key === key ? value.frame : null,
    message: !id
      ? "Invalid review address. Select an observed state in the controls."
      : value.key === key
        ? value.message
        : "Verifying this observed state against your live access…",
  };
}
