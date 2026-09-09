"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { ActionButton } from "@ac/ui";
import { ArrowRight, CopyPlus, LoaderCircle, ShieldCheck } from "lucide-react";
import {
  AdminApiProblem,
  createStudioRevision,
  newIdempotencyKey,
  type StudioProgramDetail,
} from "../admin-api";
import {
  clearStudioRevision,
  readStudioRevision,
  retainStudioRevision,
  type StudioRevisionCommand,
} from "./studio-draft-recovery";
import styles from "./studio-course-editor.module.css";

type Version = StudioProgramDetail["versions"][number];

/** A revision is a distinct, audited draft, never an edit to live lessons. */
export function StudioRevisionAction({
  program,
  source,
  canWrite,
  disabled,
  recoveryContext,
  onPendingChange,
  onOpenVersion,
  onCreated,
}: {
  program: StudioProgramDetail;
  source?: Version;
  canWrite: boolean;
  disabled: boolean;
  recoveryContext: string;
  onPendingChange: (pending: boolean) => void;
  onOpenVersion: (version: Version) => void;
  onCreated: (program: StudioProgramDetail, versionId: string) => void;
}) {
  const [command, setCommand] = useState<StudioRevisionCommand | null>(() =>
    readStudioRevision(recoveryContext, program.id),
  );
  const [state, setState] = useState<
    "idle" | "confirm" | "saving" | "unknown" | "error"
  >(command ? "unknown" : "idle");
  const [message, setMessage] = useState("");
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Aborting observation cannot undo a server command. Its exact intent
      // was retained before sending and remains available on re-entry.
      controller.current?.abort();
    };
  }, []);

  const writable =
    canWrite &&
    program.access === "selected_tenant" &&
    program.scope === "tenant";
  const available = writable && source?.status === "published" && !!source.etag;
  const existingDraft =
    source &&
    program.versions.find(
      (item) =>
        item.status === "draft" && item.supersedes_version_id === source.id,
    );
  if (!command && !available) return null;

  async function create() {
    if (!writable || inFlight.current || (!command && (!available || disabled)))
      return;
    const intent = command ?? {
      programVersionId: source!.id,
      ifMatch: source!.etag!,
      idempotencyKey: newIdempotencyKey(),
    };
    retainStudioRevision(recoveryContext, program.id, intent);
    setCommand(intent);
    inFlight.current = true;
    controller.current = new AbortController();
    setState("saving");
    setMessage("");
    onPendingChange(true);
    try {
      const result = await createStudioRevision({
        ...intent,
        programId: program.id,
        tenantId: program.tenant_id,
        signal: controller.current.signal,
      });
      if (!mounted.current) return;
      onCreated(result.program, result.resource_id);
      clearStudioRevision(recoveryContext, program.id);
      setCommand(null);
      setState("idle");
      onPendingChange(false);
    } catch (error) {
      if (!mounted.current) return;
      if (
        error instanceof AdminApiProblem &&
        error.status >= 400 &&
        error.status < 500
      ) {
        if (command && [401, 403, 404, 410].includes(error.status)) {
          // Fresh authorization runs before receipt lookup. A denied replay
          // says nothing about whether the earlier request committed.
          setState("unknown");
          setMessage(
            "Your editing access could not be confirmed. The earlier request may already have created a revision; its exact request is kept here while you check your access.",
          );
          return;
        }
        clearStudioRevision(recoveryContext, program.id);
        setCommand(null);
        setState("error");
        onPendingChange(false);
        setMessage(
          [401, 403, 404, 410].includes(error.status)
            ? "Your editing access could not be confirmed. Sign in again or reopen this course to check your access."
            : [409, 412].includes(error.status)
              ? "This course changed before the revision could be created. Reopen the course to load its current version."
              : "The revision request was not accepted. Reopen the course and try again.",
        );
      } else {
        setState("unknown");
        setMessage("");
      }
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <section
      className={styles.revisionPanel}
      aria-label="Course revision"
      aria-busy={state === "saving"}
    >
      <div className={styles.revisionIcon} aria-hidden="true">
        <CopyPlus size={23} />
      </div>
      <div className={styles.revisionContent}>
        <h3>
          {command
            ? "Confirm your new revision"
            : existingDraft
              ? "Your next version is in progress"
              : "Ready to improve this course?"}
        </h3>
        <p>
          {command
            ? "We haven’t confirmed the result yet. Check this same request before starting another revision."
            : existingDraft
              ? `Draft v${existingDraft.version_number} already builds on this published version. Continue editing it without changing live lessons.`
              : "Create an editable copy of the published course. Learners keep their current version while you work."}
        </p>
        {state === "confirm" ? (
          <div className={styles.revisionDetails}>
            <p>
              Module order, prerequisites, activity types, titles, and
              instructions will be copied. Videos and other media need to be
              connected to the new activities separately.
            </p>
            <p>
              <ShieldCheck size={17} aria-hidden="true" /> The revision needs a
              fresh content review before publication. This does not move
              learners or change their progress.
            </p>
          </div>
        ) : null}
        <div role="status" aria-live="polite">
          {state === "saving" ? <p>Creating your revision…</p> : null}
          {message ? <p>{message}</p> : null}
          {command && !writable ? (
            <p>
              Editing access is unavailable. Your request is kept in this tab
              while you check your access.
            </p>
          ) : null}
        </div>
      </div>
      <div className={styles.revisionActions}>
        {command ? (
          <ActionButton
            disabled={!writable || state === "saving"}
            onClick={() => void create()}
          >
            {state === "saving" ? (
              <LoaderCircle
                className={styles.revisionSpinner}
                size={18}
                aria-hidden="true"
              />
            ) : null}
            {state === "saving" ? "Creating revision…" : "Check revision"}
          </ActionButton>
        ) : state === "error" ? (
          <a
            className={styles.revisionReload}
            href={`/studio/programs/${program.id}`}
          >
            Reopen course <ArrowRight size={16} aria-hidden="true" />
          </a>
        ) : existingDraft ? (
          <ActionButton
            disabled={disabled}
            onClick={() => onOpenVersion(existingDraft)}
          >
            Open draft v{existingDraft.version_number}{" "}
            <ArrowRight size={16} aria-hidden="true" />
          </ActionButton>
        ) : state === "confirm" ? (
          <>
            <ActionButton disabled={disabled} onClick={() => void create()}>
              Create draft revision
            </ActionButton>
            <ActionButton variant="quiet" onClick={() => setState("idle")}>
              Not now
            </ActionButton>
          </>
        ) : (
          <ActionButton
            variant="secondary"
            disabled={disabled}
            onClick={() => setState("confirm")}
          >
            <CopyPlus size={17} aria-hidden="true" /> Create editable revision
          </ActionButton>
        )}
      </div>
    </section>
  );
}
