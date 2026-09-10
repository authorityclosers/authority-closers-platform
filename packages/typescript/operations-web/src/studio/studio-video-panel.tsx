"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { ActionButton } from "@ac/ui";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Film,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { AdminApiProblem, newIdempotencyKey } from "../admin-api";
import {
  loadStudioActivityVideo,
  loadStudioVideos,
  saveStudioActivityVideo,
  studioVideoSelectionSchema,
  type StudioActivityVideo,
  type StudioVideoChoice,
  type StudioVideoPage,
  type StudioVideoSelection,
} from "./studio-video-api";
import styles from "./studio-video-panel.module.css";
import { StudioVideoPreview } from "./studio-video-preview";

export type StudioVideoPanelProps = {
  programId: string;
  activityId: string;
  versionStatus: string;
  canWrite: boolean;
  recoveryContext: string;
  libraryRevision?: number;
  onPendingChange?: (pending: boolean) => void;
};

type Pending = {
  selection: StudioVideoSelection;
  idempotencyKey: string;
  label: string;
};

// Like Studio draft recovery, this is browser-only, same-document intent.
// It never persists to storage/cookies or supplies authorization. Unresolved
// commands cannot expire/evict silently: that would permit a duplicate command.
let recoveryScope = "";
const pendingCommands = new Map<string, Pending>();
const maximumPending = 20;

/** Call with the current session/tenant scope, or an empty string on logout. */
export function activateStudioVideoRecoveryScope(context: string) {
  if (typeof window === "undefined" || context === recoveryScope) return;
  pendingCommands.clear();
  recoveryScope = context;
}

/** Navigation hint only; filenames, approval text and authority stay private. */
export function readStudioVideoRecoveryActivity(
  context: string,
  programId: string,
): string | null {
  if (typeof window === "undefined" || !context || context !== recoveryScope)
    return null;
  const prefix = `${programId}:`;
  const key = [...pendingCommands.keys()].find((candidate) =>
    candidate.startsWith(prefix),
  );
  return key ? key.slice(prefix.length) : null;
}

function readPending(context: string, key: string): Pending | null {
  if (typeof window === "undefined" || !context || context !== recoveryScope)
    return null;
  const pending = pendingCommands.get(key);
  return pending ? structuredClone(pending) : null;
}

function retainPending(context: string, key: string, pending: Pending) {
  if (typeof window === "undefined" || !context || context !== recoveryScope) {
    throw new Error("The video recovery context is unavailable.");
  }
  if (!pendingCommands.has(key) && pendingCommands.size >= maximumPending) {
    throw new Error("Check an earlier video request before starting another.");
  }
  pendingCommands.set(key, structuredClone(pending));
}

function clearPending(context: string, key: string, command: Pending) {
  if (
    context === recoveryScope &&
    pendingCommands.get(key)?.idempotencyKey === command.idempotencyKey
  ) {
    pendingCommands.delete(key);
  }
}

function editable(status: string) {
  return status === "published" || status === "superseded";
}

function readFailure(error: unknown) {
  return accessDenied(error)
    ? "Your editing access could not be confirmed. Sign in again or reopen this course."
    : "Video details could not be loaded. Try again when your connection is available.";
}

function accessDenied(error: unknown) {
  return (
    error instanceof AdminApiProblem &&
    [401, 403, 404, 410].includes(error.status)
  );
}

function details(choice: StudioVideoChoice) {
  const parts = [`Version ${choice.version_number}`];
  if (choice.duration_seconds !== null) {
    const seconds = Math.round(choice.duration_seconds);
    parts.push(
      `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`,
    );
  }
  if (choice.width !== null && choice.height !== null)
    parts.push(`${choice.width} × ${choice.height}`);
  if (choice.actual_bytes !== null) {
    parts.push(
      choice.actual_bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(choice.actual_bytes / 1024))} KB`
        : `${(choice.actual_bytes / (1024 * 1024)).toFixed(1)} MB`,
    );
  }
  return parts.join(" · ");
}

/** The inner key also isolates late promises when a caller forgets to remount. */
export function StudioVideoPanel(props: StudioVideoPanelProps) {
  return (
    <VideoPanelSession
      key={`${props.recoveryContext}:${props.programId}:${props.activityId}:${props.versionStatus}:${props.canWrite}`}
      {...props}
    />
  );
}

function VideoPanelSession({
  programId,
  activityId,
  versionStatus,
  canWrite,
  recoveryContext,
  libraryRevision = 0,
  onPendingChange,
}: StudioVideoPanelProps) {
  const id = useId();
  const recoveryKey = `${programId}:${activityId}`;
  const [command, setCommand] = useState<Pending | null>(() =>
    readPending(recoveryContext, recoveryKey),
  );
  const [current, setCurrent] = useState<StudioActivityVideo | null>(null);
  const [page, setPage] = useState<StudioVideoPage | null>(null);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [selected, setSelected] = useState<StudioVideoChoice | null>(null);
  const [approval, setApproval] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mustRefresh, setMustRefresh] = useState(false);
  const [denied, setDenied] = useState(false);
  const alive = useRef(false);
  const busy = useRef(false);
  const pendingCallback = useRef(onPendingChange);
  const readSequence = useRef(0);
  const readController = useRef<AbortController | null>(null);
  const writeController = useRef<AbortController | null>(null);
  const previousLibraryRevision = useRef(libraryRevision);
  const eligible = canWrite && !!recoveryContext && editable(versionStatus);
  const writable =
    eligible && !denied && current !== null && editable(current.version_status);
  const frozen = saving || !!command || loading || mustRefresh;

  useLayoutEffect(() => {
    pendingCallback.current = onPendingChange;
  });

  useLayoutEffect(() => {
    if (
      previousLibraryRevision.current === libraryRevision ||
      command ||
      selected ||
      loading ||
      busy.current
    )
      return;
    previousLibraryRevision.current = libraryRevision;
    void refresh();
    // Refresh only after an upload, without replacing an unsaved selection or command.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryRevision, command, selected, loading]);

  useLayoutEffect(() => {
    pendingCallback.current?.(command !== null || saving);
  }, [command, saving]);

  useLayoutEffect(() => {
    alive.current = true;
    activateStudioVideoRecoveryScope(recoveryContext);
    if (eligible) void refresh();
    return () => {
      alive.current = false;
      readSequence.current += 1;
      readController.current?.abort();
      writeController.current?.abort();
      pendingCallback.current?.(false);
    };
    // The public wrapper remounts for every authority/resource prop change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useLayoutEffect(() => {
    if (!command) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [command]);

  function hideDeniedAccess() {
    setDenied(true);
    setCurrent(null);
    setPage(null);
    setSelected(null);
    setApproval("");
    setNotice("");
    setMustRefresh(true);
    // Pending intent stays private for exact receipt recovery. It is not an
    // authorization to retain its filename/reference in the rendered view.
  }

  async function refresh() {
    if (!eligible || busy.current) return;
    const sequence = ++readSequence.current;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    setLoading(true);
    setMustRefresh(true);
    setError("");
    try {
      const result = await loadStudioActivityVideo({
        programId,
        activityId,
        signal: controller.signal,
      });
      if (!alive.current || sequence !== readSequence.current) return;
      setCurrent(result);
      if (!editable(result.version_status)) {
        setPage(null);
        setDenied(false);
        setLoading(false);
        return;
      }
      const videos = await loadStudioVideos({
        programId,
        signal: controller.signal,
      });
      if (!alive.current || sequence !== readSequence.current) return;
      setPage(videos);
      setCursors([null]);
      setSelected(null);
      setMustRefresh(false);
      setDenied(false);
    } catch (failure) {
      if (alive.current && sequence === readSequence.current) {
        if (accessDenied(failure)) hideDeniedAccess();
        setError(readFailure(failure));
      }
    } finally {
      if (alive.current && sequence === readSequence.current) setLoading(false);
    }
  }

  async function changePage(next: (string | null)[]) {
    if (!writable || frozen) return;
    const sequence = ++readSequence.current;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    setLoading(true);
    setError("");
    try {
      const result = await loadStudioVideos({
        programId,
        after: next.at(-1) ?? null,
        signal: controller.signal,
      });
      if (!alive.current || sequence !== readSequence.current) return;
      setPage(result);
      setCursors(next);
    } catch (failure) {
      if (alive.current && sequence === readSequence.current) {
        if (accessDenied(failure)) hideDeniedAccess();
        setError(readFailure(failure));
      }
    } finally {
      if (alive.current && sequence === readSequence.current) setLoading(false);
    }
  }

  async function save() {
    if (!writable || busy.current || loading || (!command && mustRefresh))
      return;
    const retry = command !== null;
    let intent = command;
    if (!intent) {
      if (!selected) return;
      const parsed = studioVideoSelectionSchema.safeParse({
        asset_id: selected.asset_id,
        version_id: selected.version_id,
        expected_binding_id: current.binding?.binding_id ?? null,
        approval_reference: approval.trim(),
      });
      if (!parsed.success) {
        setError(
          "Add a short approval reference without control characters (up to 200 characters).",
        );
        return;
      }
      try {
        intent = {
          selection: parsed.data,
          idempotencyKey: newIdempotencyKey(),
          label: selected.label,
        };
        retainPending(recoveryContext, recoveryKey, intent);
      } catch {
        setError(
          "The request could not be safely retained. Reopen the course or check an earlier video request.",
        );
        return;
      }
      setCommand(intent);
    }
    busy.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    const controller = new AbortController();
    writeController.current = controller;
    try {
      const result = await saveStudioActivityVideo({
        programId,
        activityId,
        selection: intent.selection,
        idempotencyKey: intent.idempotencyKey,
        signal: controller.signal,
      });
      clearPending(recoveryContext, recoveryKey, intent);
      if (!alive.current) return;
      setCommand(null);
      setSelected(null);
      setApproval("");
      if (result.state === "approved") {
        setCurrent({
          activity_id: activityId,
          version_status: current.version_status,
          binding: {
            binding_id: result.binding_id,
            asset_id: result.asset_id,
            version_id: result.version_id,
            label: intent.label,
            state: "approved",
          },
        });
        setNotice(
          result.replayed
            ? "Your video request is confirmed."
            : "Video approved for this lesson.",
        );
      } else {
        setMustRefresh(true);
        setNotice(
          "Your request is confirmed, but that binding has since changed. Refresh the lesson to see its current video.",
        );
      }
    } catch (failure) {
      if (!alive.current) return;
      if (accessDenied(failure)) hideDeniedAccess();
      if (
        !retry &&
        failure instanceof AdminApiProblem &&
        [400, 401, 403, 404, 409, 410, 412, 422].includes(failure.status)
      ) {
        clearPending(recoveryContext, recoveryKey, intent);
        setCommand(null);
        setMustRefresh(true);
        setError(
          [409, 412].includes(failure.status)
            ? "This lesson or video changed before approval. Refresh the lesson, then review your selection."
            : [401, 403, 404, 410].includes(failure.status)
              ? "Your editing access could not be confirmed. Sign in again or reopen this course."
              : "The approval was not accepted. Refresh the lesson before trying again.",
        );
      } else {
        setError(
          failure instanceof AdminApiProblem &&
            [401, 403, 404, 410].includes(failure.status)
            ? "Editing access is unavailable. The earlier request may already have completed; its exact intent is kept in this tab."
            : "We could not confirm the result. Retry this same approval before choosing another video.",
        );
      }
    } finally {
      busy.current = false;
      if (alive.current) setSaving(false);
    }
  }

  async function recoverCurrent() {
    if (!command || !eligible || busy.current || loading) return;
    const intent = command;
    const sequence = ++readSequence.current;
    const controller = new AbortController();
    readController.current?.abort();
    readController.current = controller;
    setLoading(true);
    setError("");
    try {
      const result = await loadStudioActivityVideo({
        programId,
        activityId,
        signal: controller.signal,
      });
      if (!alive.current || sequence !== readSequence.current) return;
      setCurrent(result);
      // Current state is not a command receipt: our earlier approval may have
      // committed and then been superseded. Retain the exact request until its
      // POST receipt is confirmed, including historical superseded/revoked ones.
      if (
        (result.binding?.binding_id ?? null) !==
        intent.selection.expected_binding_id
      ) {
        setNotice(
          "The current lesson video has changed. Retry the same approval to confirm what happened to your earlier request.",
        );
      } else {
        setNotice(
          "The lesson still shows its previous video state. Retry the same approval to confirm its outcome.",
        );
      }
    } catch (failure) {
      if (alive.current && sequence === readSequence.current) {
        if (accessDenied(failure)) hideDeniedAccess();
        setError(readFailure(failure));
      }
    } finally {
      if (alive.current && sequence === readSequence.current) setLoading(false);
    }
  }

  const readOnlyMessage = !canWrite
    ? "Editing access is required to choose a lesson video."
    : !recoveryContext
      ? "Reopen this course to confirm your editing session."
      : denied
        ? "Your editing access could not be confirmed. Sign in again or reopen this course."
        : versionStatus === "draft"
          ? "Video approval is available for published course versions. Publish through the course’s review process before connecting this draft activity."
          : !editable(versionStatus) ||
              (current && !editable(current.version_status))
            ? "Video approval is unavailable for this course version. Reopen the course to check its status."
            : null;

  return (
    <section
      className={styles.panel}
      aria-labelledby={`${id}-title`}
      aria-busy={loading || saving}
    >
      <header className={styles.header}>
        <span className={styles.icon} aria-hidden="true">
          <Film size={22} />
        </span>
        <div>
          <span className={styles.eyebrow}>Lesson source</span>
          <h3 id={`${id}-title`}>Lesson video</h3>
        </div>
      </header>
      {readOnlyMessage ? (
        <>
          <p className={styles.muted} role={denied ? "alert" : undefined}>
            {readOnlyMessage}
          </p>
          {denied && eligible ? (
            <ActionButton
              variant="secondary"
              disabled={loading || saving}
              onClick={() => void refresh()}
            >
              {loading ? "Checking editing access…" : "Check editing access"}
            </ActionButton>
          ) : null}
        </>
      ) : (
        <>
          <div className={styles.current}>
            <span className={styles.eyebrow}>Current video</span>
            <p>
              {current
                ? (current.binding?.label ??
                  "No video approved for this lesson yet.")
                : "Checking the current lesson…"}
            </p>
            {current?.binding ? (
              <span className={styles.badge}>
                <ShieldCheck size={15} aria-hidden="true" /> Approved
              </span>
            ) : null}
            {current?.binding ? (
              <StudioVideoPreview
                programId={programId}
                assetId={current.binding.asset_id}
                versionId={current.binding.version_id}
                label={current.binding.label}
                recoveryContext={recoveryContext}
              />
            ) : null}
          </div>
          {command && writable ? (
            <div className={styles.recovery}>
              <h4>
                {saving
                  ? "Confirming your approval"
                  : "Check your video approval"}
              </h4>
              <p>{command.label}</p>
              <p className={styles.muted}>
                Approval reference: {command.selection.approval_reference}
              </p>
              <p className={styles.muted}>
                The exact selection and approval reference are kept in this tab
                until the outcome is confirmed. Leave this tab open.
              </p>
              <div className={styles.actions}>
                <ActionButton
                  disabled={!writable || saving || loading}
                  onClick={() => void save()}
                >
                  {saving ? (
                    <LoaderCircle
                      className={styles.spinner}
                      size={17}
                      aria-hidden="true"
                    />
                  ) : null}
                  {saving ? "Confirming approval…" : "Retry same approval"}
                </ActionButton>
                <ActionButton
                  variant="secondary"
                  disabled={saving || loading || !eligible}
                  onClick={() => void recoverCurrent()}
                >
                  Check current lesson
                </ActionButton>
              </div>
            </div>
          ) : null}
          {command && !writable ? (
            <p role="status" className={styles.muted}>
              An earlier video request is unresolved. Checking editing access
              before showing its details.
            </p>
          ) : null}
          {loading ? (
            <p role="status" className={styles.loading}>
              <LoaderCircle
                className={styles.spinner}
                size={17}
                aria-hidden="true"
              />{" "}
              Loading video details…
            </p>
          ) : null}
          {page && writable ? (
            <>
              <fieldset className={styles.picker} disabled={frozen}>
                <legend>Choose an available video</legend>
                <p className={styles.muted}>
                  Your ready uploads and videos already approved for this
                  course. Check the source before approving it.
                </p>
                {page.items.length === 0 ? (
                  <div className={styles.empty}>
                    <Film size={26} aria-hidden="true" />
                    <h4>No ready videos available</h4>
                    <p>
                      A ready upload you own or a video approved for this course
                      will appear here.
                    </p>
                  </div>
                ) : (
                  <div className={styles.grid}>
                    {page.items.map((choice) => (
                      <label
                        key={choice.asset_id}
                        className={styles.choice}
                        data-selected={selected?.asset_id === choice.asset_id}
                      >
                        <input
                          type="radio"
                          name={`${id}-video`}
                          value={choice.asset_id}
                          checked={selected?.asset_id === choice.asset_id}
                          onChange={() => {
                            setSelected(choice);
                            setError("");
                            setNotice("");
                          }}
                        />
                        <span className={styles.choiceBody}>
                          <strong>{choice.label}</strong>
                          <span>{details(choice)}</span>
                          {current.binding?.asset_id === choice.asset_id &&
                          current.binding.version_id === choice.version_id ? (
                            <span className={styles.currentHint}>
                              Used in this lesson
                            </span>
                          ) : null}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </fieldset>
              {cursors.length > 1 || page.next_cursor ? (
                <nav className={styles.pagination} aria-label="Video pages">
                  <ActionButton
                    variant="quiet"
                    disabled={frozen || cursors.length === 1}
                    onClick={() => void changePage(cursors.slice(0, -1))}
                  >
                    <ChevronLeft size={17} aria-hidden="true" /> Previous videos
                  </ActionButton>
                  <span>Page {cursors.length}</span>
                  <ActionButton
                    variant="quiet"
                    disabled={frozen || !page.next_cursor}
                    onClick={() =>
                      void changePage([...cursors, page.next_cursor])
                    }
                  >
                    Next videos <ChevronRight size={17} aria-hidden="true" />
                  </ActionButton>
                </nav>
              ) : null}
              {selected && !command ? (
                <div className={styles.approval}>
                  <h4>Approve “{selected.label}”</h4>
                  <StudioVideoPreview
                    programId={programId}
                    assetId={selected.asset_id}
                    versionId={selected.version_id}
                    label={selected.label}
                    recoveryContext={recoveryContext}
                  />
                  <label htmlFor={`${id}-approval`}>Approval reference</label>
                  <input
                    id={`${id}-approval`}
                    value={approval}
                    disabled={frozen}
                    maxLength={200}
                    onChange={(event) => setApproval(event.target.value)}
                    aria-describedby={`${id}-approval-help`}
                    placeholder="For example: Content review, 9 September"
                  />
                  <p id={`${id}-approval-help`} className={styles.muted}>
                    Record the human review that approves this source for the
                    lesson.
                  </p>
                  <ActionButton
                    disabled={frozen || !approval.trim()}
                    onClick={() => void save()}
                  >
                    <ShieldCheck size={17} aria-hidden="true" />{" "}
                    {current.binding
                      ? "Approve replacement video"
                      : "Approve lesson video"}
                  </ActionButton>
                </div>
              ) : null}
            </>
          ) : null}
          <div aria-live="polite" aria-atomic="true">
            {error ? (
              <p role="alert" className={styles.error}>
                {error}
              </p>
            ) : null}
            {notice ? (
              <p role="status" className={styles.notice}>
                <Check size={17} aria-hidden="true" />
                {notice}
              </p>
            ) : null}
          </div>
          {!command && !loading ? (
            <ActionButton variant="quiet" onClick={() => void refresh()}>
              {mustRefresh
                ? "Refresh lesson"
                : error
                  ? "Retry loading videos"
                  : "Refresh videos"}
            </ActionButton>
          ) : null}
        </>
      )}
      {readOnlyMessage && command ? (
        <p role="status" className={styles.muted}>
          An earlier video request is unresolved. Its exact intent is kept in
          this tab while you restore editing access.
        </p>
      ) : null}
    </section>
  );
}
