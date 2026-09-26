"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { parseProgress, parseSubmission, UUID } from "./acquisition-client";
import { fixtureFrame, fixtureStateId } from "./fixture-review-states";
import type {
  LocalReviewObservation,
  ProcessingReview,
  ReviewNavigation,
} from "./processing-review-port";

const REVIEW_PATH = "/__review/api/frames/";
const LOCAL_REVIEW_PATH = "/__review/api/local/frames/";
const REVIEW_CATALOG_PATH = "/__review/api/catalog";
const LOCAL_CATALOG_PATH = "/__review/api/local/catalog";
const MAX_LOCAL_LIFETIME_MS = 31 * 60_000;

function catalogFrameIds(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const frames = (value as Record<string, unknown>).frames;
  if (!Array.isArray(frames) || frames.length > 128) return null;
  const result: { id: string; state: string }[] = [];
  const seen = new Set<string>();
  for (const item of frames) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const frame = item as Record<string, unknown>;
    if (
      typeof frame.id !== "string" ||
      !UUID.test(frame.id) ||
      seen.has(frame.id) ||
      typeof frame.state !== "string" ||
      frame.state.length > 128
    )
      return null;
    seen.add(frame.id);
    result.push({ id: frame.id, state: frame.state });
  }
  return result;
}

function navigationFor(
  frames: { id: string; state: string }[] | null,
  id: string,
  href: (frame: { id: string; state: string }) => string,
): ReviewNavigation | null {
  if (!frames) return null;
  const index = frames.findIndex((frame) => frame.id === id);
  if (index < 0) return null;
  return {
    previousUrl: index > 0 ? href(frames[index - 1]) : null,
    nextUrl: index + 1 < frames.length ? href(frames[index + 1]) : null,
    position: index + 1,
    total: frames.length,
  };
}

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  window.addEventListener("popstate", listener);
  return () => {
    window.removeEventListener("hashchange", listener);
    window.removeEventListener("popstate", listener);
  };
}

function routeSnapshot() {
  return `${window.location.search}\u0000${window.location.hash}`;
}

function activeReviewSelection() {
  const search = new URLSearchParams(window.location.search);
  return (
    window.location.hash.startsWith("#sx-review=") ||
    search.has("sx-review-local") ||
    search.has("sx-fixture")
  );
}

function parseRouteSnapshot(value: string) {
  const separator = value.indexOf("\u0000");
  return {
    search: separator < 0 ? "" : value.slice(0, separator),
    hash: separator < 0 ? value : value.slice(separator + 1),
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

export function localReviewFrameId(search: string): string | null {
  const params = new URLSearchParams(search);
  if (
    params.getAll("sx-review-local").length !== 1 ||
    params.getAll("new").length !== 1 ||
    params.get("new") !== "1" ||
    [...params.keys()].some((key) => !["new", "sx-review-local"].includes(key))
  )
    return null;
  const id = params.get("sx-review-local");
  return id && UUID.test(id) ? id : null;
}

export function parseLocalReviewObservation(
  value: unknown,
): LocalReviewObservation | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).length !== 7 ||
    ![
      "upload.empty",
      "upload.file.selected",
      "upload.validation.error",
    ].includes(String(item.phase)) ||
    typeof item.privacy_open !== "boolean" ||
    typeof item.consent_checked !== "boolean" ||
    ![null, "en", "hi-Deva+en", "mr-Deva+en"].includes(
      item.report_language as string | null,
    ) ||
    ![
      "checking",
      "session-present",
      "guest-challenge-required",
      "guest-challenge-complete",
    ].includes(String(item.verification)) ||
    !(
      item.file_name === null ||
      (typeof item.file_name === "string" &&
        item.file_name.length > 0 &&
        item.file_name.length <= 255 &&
        !/[\u0000-\u001f\u007f]/.test(item.file_name))
    ) ||
    !(
      item.file_size_bytes === null ||
      (Number.isSafeInteger(item.file_size_bytes) &&
        (item.file_size_bytes as number) > 0 &&
        (item.file_size_bytes as number) <= 32 * 1024 ** 2)
    ) ||
    (item.phase === "upload.file.selected" &&
      (item.file_name === null || item.file_size_bytes === null)) ||
    (item.phase === "upload.empty" &&
      (item.file_name !== null || item.file_size_bytes !== null)) ||
    (item.phase === "upload.validation.error" &&
      (item.file_name === null) !== (item.file_size_bytes === null))
  )
    return null;
  return {
    phase: item.phase as LocalReviewObservation["phase"],
    privacy_open: item.privacy_open,
    consent_checked: item.consent_checked,
    report_language:
      item.report_language as LocalReviewObservation["report_language"],
    verification: item.verification as LocalReviewObservation["verification"],
    file_name: item.file_name as string | null,
    file_size_bytes: item.file_size_bytes as number | null,
  };
}

function parseLocalReviewFrame(value: unknown, id: string) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const observation = parseLocalReviewObservation(item.observation);
  const now = Date.now();
  if (
    item.id !== id ||
    typeof item.observedAt !== "number" ||
    item.observedAt > now + 1000 ||
    typeof item.expiresAt !== "number" ||
    item.expiresAt <= now ||
    item.expiresAt > now + MAX_LOCAL_LIFETIME_MS ||
    typeof item.label !== "string" ||
    item.label.length > 512 ||
    !observation
  )
    return null;
  return {
    id,
    observedAt: item.observedAt,
    expiresAt: item.expiresAt,
    label: item.label,
    observation,
  };
}

export function useProcessingReview(callId: string | null): ProcessingReview {
  const snapshot = useSyncExternalStore(
    subscribe,
    routeSnapshot,
    () => "\u0000",
  );
  const { search, hash } = parseRouteSnapshot(snapshot);
  const requested = hash.startsWith("#sx-review=");
  const frameId = reviewFrameId(hash);
  const localRequested = new URLSearchParams(search).has("sx-review-local");
  const localFrameId = localReviewFrameId(search);
  const fixtureRequested = new URLSearchParams(search).has("sx-fixture");
  const selectedFixtureId = fixtureStateId(search);
  const [readOnly, setReadOnly] = useState<boolean | null>(null);
  const [value, setValue] = useState<{
    key: string;
    frame: ProcessingReview["frame"];
    message: string;
  }>({ key: "", frame: null, message: "" });
  const [localValue, setLocalValue] = useState<{
    key: string;
    frame: ProcessingReview["localFrame"];
    message: string;
  }>({ key: "", frame: null, message: "" });
  const localWriteQueue = useRef(Promise.resolve());
  const lastLocalObservation = useRef("");
  const key = callId + ":" + frameId;

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    async function refresh() {
      try {
        const response = await fetch("/health", {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal: abort.signal,
        });
        if (!response.ok) throw new Error("Review mode unavailable");
        const body: unknown = await response.json();
        if (
          !body ||
          typeof body !== "object" ||
          !("analysis_read_only" in body) ||
          typeof body.analysis_read_only !== "boolean"
        )
          throw new Error("Review mode unavailable");
        if (!abort.signal.aborted) setReadOnly(body.analysis_read_only);
      } catch {
        if (!abort.signal.aborted) setReadOnly(null);
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void refresh(), 5000);
    }
    void refresh();
    return () => {
      abort.abort();
      if (timer) clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!requested || !callId || !frameId || localRequested || fixtureRequested)
      return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const response = await fetch(`${REVIEW_PATH}${frameId}`, {
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
          frame: {
            submission,
            progress,
            observedAt: body.observedAt,
            navigation: null,
          },
          message: "",
        });
        const expireAt = (until: number) => {
          if (expiry) clearTimeout(expiry);
          expiry = setTimeout(
            () =>
              setValue({
                key,
                frame: null,
                message:
                  "Live access verification expired. Reopen the controls to verify access.",
              }),
            Math.max(0, until - Date.now()),
          );
        };
        expireAt(body.leaseUntil);
        timer = setTimeout(() => void refresh(), 15_000);
        void (async () => {
          try {
            const catalogResponse = await fetch(REVIEW_CATALOG_PATH, {
              credentials: "same-origin",
              cache: "no-store",
              redirect: "error",
              signal: abort.signal,
            });
            if (!catalogResponse.ok) return;
            const catalog: unknown = await catalogResponse.json();
            if (
              !catalog ||
              typeof catalog !== "object" ||
              Array.isArray(catalog) ||
              (catalog as Record<string, unknown>).callId !== callId ||
              typeof (catalog as Record<string, unknown>).leaseUntil !==
                "number" ||
              (catalog as Record<string, number>).leaseUntil <= Date.now() ||
              (catalog as Record<string, number>).leaseUntil >
                Date.now() + 31_000
            )
              return;
            const authorizedUntil = (catalog as Record<string, number>)
              .leaseUntil;
            const navigation = navigationFor(
              catalogFrameIds(catalog),
              frameId!,
              (item) =>
                item.state === "report.available"
                  ? `/?call=${callId}`
                  : `/?call=${callId}#sx-review=v1&mode=observed&frame=${item.id}`,
            );
            if (abort.signal.aborted || authorizedUntil <= Date.now()) return;
            setValue((current) =>
              current.key === key && current.frame
                ? {
                    ...current,
                    frame: { ...current.frame, navigation },
                  }
                : current,
            );
            expireAt(authorizedUntil);
          } catch {
            // The selected observation remains available only through its current lease.
          }
        })();
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
  }, [requested, callId, frameId, key, localRequested, fixtureRequested]);

  useEffect(() => {
    if (!localRequested || requested || fixtureRequested) return;
    const abort = new AbortController();
    let expiry: ReturnType<typeof setTimeout> | undefined;
    if (!localFrameId) {
      return () => abort.abort();
    }
    void (async () => {
      try {
        const response = await fetch(`${LOCAL_REVIEW_PATH}${localFrameId}`, {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal: abort.signal,
        });
        if (!response.ok)
          throw new Error(
            "This browser-local observation expired or is no longer available. Return to the controls and capture it again.",
          );
        const frame = parseLocalReviewFrame(
          await response.json(),
          localFrameId,
        );
        if (!frame)
          throw new Error("The browser-local observation is invalid.");
        if (!abort.signal.aborted) {
          setLocalValue({
            key: snapshot,
            frame: { ...frame, navigation: null },
            message: "",
          });
          expiry = setTimeout(
            () => {
              setLocalValue((current) =>
                current.key === snapshot && current.frame?.id === localFrameId
                  ? {
                      key: snapshot,
                      frame: null,
                      message:
                        "This browser-local observation expired. Return to the controls and capture it again.",
                    }
                  : current,
              );
            },
            Math.max(0, frame.expiresAt - Date.now()),
          );
        }
        try {
          const catalogResponse = await fetch(LOCAL_CATALOG_PATH, {
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
            signal: abort.signal,
          });
          if (catalogResponse.ok) {
            const navigation = navigationFor(
              catalogFrameIds(await catalogResponse.json()),
              localFrameId,
              (item) => `/?new=1&sx-review-local=${item.id}`,
            );
            if (!abort.signal.aborted)
              setLocalValue((current) =>
                current.key === snapshot && current.frame
                  ? {
                      ...current,
                      frame: { ...current.frame, navigation },
                    }
                  : current,
              );
          }
        } catch {
          // The selected observation remains open without optional navigation.
        }
      } catch (error) {
        if (!abort.signal.aborted)
          setLocalValue({
            key: snapshot,
            frame: null,
            message:
              error instanceof Error
                ? error.message
                : "The browser-local observation could not be opened.",
          });
      }
    })();
    return () => {
      abort.abort();
      if (expiry) clearTimeout(expiry);
    };
  }, [localRequested, localFrameId, requested, fixtureRequested, snapshot]);

  const captureLocal = useCallback(
    (observation: LocalReviewObservation) => {
      if (readOnly !== true || activeReviewSelection()) return;
      const serialized = JSON.stringify(observation);
      if (serialized === lastLocalObservation.current) return;
      lastLocalObservation.current = serialized;
      localWriteQueue.current = localWriteQueue.current.then(async () => {
        try {
          const response = await fetch("/__review/api/local/observe", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ observation }),
          });
          if (!response.ok && lastLocalObservation.current === serialized)
            lastLocalObservation.current = "";
        } catch {
          if (lastLocalObservation.current === serialized)
            lastLocalObservation.current = "";
        }
      });
    },
    [readOnly],
  );

  const frame = requested && value.key === key ? value.frame : null;
  const localFrame =
    localRequested && !requested && localValue.key === snapshot
      ? localValue.frame
      : null;
  const selectedFixtureFrame =
    fixtureRequested &&
    !requested &&
    !localRequested &&
    readOnly === true &&
    selectedFixtureId
      ? fixtureFrame(selectedFixtureId)
      : null;
  const message =
    [requested, localRequested, fixtureRequested].filter(Boolean).length > 1
      ? "Choose one observed state address. Remove either the review hash or browser-local selector."
      : fixtureRequested
        ? !selectedFixtureId
          ? "Invalid local fixture address. Choose a listed state in the review controls."
          : readOnly === true
            ? ""
            : readOnly === false
              ? "Local fixture states require the read-only review bridge."
              : "Checking local review availability…"
        : requested
          ? !frameId
            ? "Invalid review address. Select an observed state in the controls."
            : value.key === key
              ? value.message
              : "Verifying this observed state against your live access…"
          : localRequested
            ? !localFrameId
              ? "Invalid browser-local state address. Choose an observed state in the controls."
              : localValue.key === snapshot
                ? localValue.message ||
                  "Opening the observed browser-local state…"
                : "Opening the observed browser-local state…"
            : "";
  return {
    requested,
    frame,
    localRequested,
    localFrame,
    fixtureRequested,
    fixtureFrame: selectedFixtureFrame,
    readOnly,
    captureLocal,
    message,
  };
}
