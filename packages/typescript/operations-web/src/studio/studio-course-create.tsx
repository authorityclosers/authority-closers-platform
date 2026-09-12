"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import { ActionButton, LearningSymbol } from "@ac/ui";
import { ArrowRight, CheckCircle2, LoaderCircle, Plus, X } from "lucide-react";
import {
  AdminApiProblem,
  createStudioCourse,
  newIdempotencyKey,
  type StudioDraftMutationResponse,
} from "../admin-api";
import { canUseStudioPermission, useAdminSession } from "../admin-session";
import shared from "./studio-course-editor.module.css";
import styles from "./studio-course-create.module.css";

type Intent = { title: string; idempotencyKey: string };
type Recovery = {
  title: string;
  commandKey: string | null;
  intent: Intent | null;
  result: StudioDraftMutationResponse | null;
};
// Same-document recovery only. Never store private titles or command keys in a
// shared cache/localStorage; changing a verified identity clears the old draft.
let recovery: { scope: string; data: Recovery } | null = null;

export function activateStudioCourseCreationScope(scope: string) {
  if (scope && recovery?.scope !== scope)
    recovery = {
      scope,
      data: { title: "", commandKey: null, intent: null, result: null },
    };
}

export function StudioCourseCreate({ onRefresh }: { onRefresh?: () => void }) {
  const session = useAdminSession();
  const scope =
    session.status === "ready"
      ? JSON.stringify([
          session.session.tenantId,
          session.session.personId,
          session.session.sessionId,
        ])
      : "";
  useLayoutEffect(() => {
    activateStudioCourseCreationScope(scope);
  }, [scope]);
  if (session.status !== "ready") return null;
  const canCreate =
    canUseStudioPermission(session, "catalog_write") &&
    canUseStudioPermission(session, "catalog_read");
  return (
    <CourseCreateForm
      key={scope}
      scope={scope}
      tenantId={session.session.tenantId}
      canCreate={canCreate}
      onRefresh={onRefresh}
    />
  );
}

function CourseCreateForm({
  scope,
  tenantId,
  canCreate,
  onRefresh,
}: {
  scope: string;
  tenantId: string;
  canCreate: boolean;
  onRefresh?: () => void;
}) {
  const saved = recovery?.scope === scope ? recovery.data : null;
  const [title, setTitle] = useState(saved?.title ?? "");
  const [intent, setIntent] = useState<Intent | null>(saved?.intent ?? null);
  const [result, setResult] = useState(saved?.result ?? null);
  const [open, setOpen] = useState(Boolean(saved?.intent));
  const [state, setState] = useState<"idle" | "saving" | "unknown" | "error">(
    saved?.intent ? "unknown" : "idle",
  );
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const busy = useRef(false);
  const commandKey = useRef(saved?.commandKey ?? null);
  const mounted = useRef(false);
  const headingId = useId();
  const helpId = useId();
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useLayoutEffect(() => {
    recovery = {
      scope,
      data: { title, commandKey: commandKey.current, intent, result },
    };
  }, [scope, title, intent, result]);
  useEffect(() => {
    if (open && canCreate) {
      dialog.current?.showModal();
      if (result) heading.current?.focus();
      else if (!intent) input.current?.focus();
    } else dialog.current?.close();
  }, [open, canCreate, intent, result]);
  useEffect(() => {
    if (!title.trim() && !intent) return;
    if (result) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [title, intent, result]);

  function close() {
    if (busy.current) return;
    setOpen(false);
    if (result) {
      commandKey.current = null;
      recovery = {
        scope,
        data: { title: "", commandKey: null, intent: null, result: null },
      };
      setResult(null);
      setTitle("");
      onRefresh?.();
    }
    trigger.current?.focus();
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canCreate || busy.current || result || (!intent && !title.trim()))
      return;
    let command = intent;
    try {
      command ??= { title: title.trim(), idempotencyKey: newIdempotencyKey() };
    } catch {
      setMessage(
        "Your browser couldn’t prepare a safe request. Keep this title and try again.",
      );
      return;
    }
    const retrying = Boolean(intent);
    commandKey.current = command.idempotencyKey;
    recovery = {
      scope,
      data: {
        title,
        commandKey: command.idempotencyKey,
        intent: command,
        result: null,
      },
    };
    setIntent(command);
    busy.current = true;
    setState("saving");
    setMessage("");
    try {
      const next = await createStudioCourse({ ...command, tenantId });
      // A same-session remount can retry this command, resolve it, then start
      // another course before this original request returns. Retain the key
      // even after success so duplicate receipts cannot replace a newer intent.
      if (
        recovery?.scope !== scope ||
        recovery.data.commandKey !== command.idempotencyKey
      )
        return;
      recovery.data = {
        title: command.title,
        commandKey: command.idempotencyKey,
        intent: null,
        result: next,
      };
      if (!mounted.current || commandKey.current !== command.idempotencyKey)
        return;
      setResult(next);
      setIntent(null);
      setState("idle");
    } catch (error) {
      if (
        !mounted.current ||
        recovery?.scope !== scope ||
        recovery.data.commandKey !== command.idempotencyKey ||
        commandKey.current !== command.idempotencyKey
      )
        return;
      const definitive =
        error instanceof AdminApiProblem &&
        error.status >= 400 &&
        error.status < 500;
      if (definitive && !retrying) {
        commandKey.current = null;
        setIntent(null);
        setState("error");
        setMessage(
          [401, 403].includes(error.status)
            ? "Your course-creation access couldn’t be confirmed. Your title is kept here while you check your account."
            : "This request wasn’t accepted. Your title is kept here; check it and try again.",
        );
      } else {
        // A denied retry is not proof the earlier request failed. Preserve the
        // original title/key until that exact command's receipt is confirmed.
        setState("unknown");
        setMessage(
          "We haven’t confirmed the save. Check the same request to avoid creating a duplicate course.",
        );
      }
    } finally {
      busy.current = false;
    }
  }

  if (!canCreate) return null;
  return (
    <div className={shared.workspace}>
      <ActionButton
        ref={trigger}
        onClick={() => setOpen(true)}
        variant={intent ? "secondary" : "primary"}
      >
        {intent ? (
          <LoaderCircle size={18} aria-hidden="true" />
        ) : (
          <Plus size={18} aria-hidden="true" />
        )}
        {intent
          ? "Check course creation"
          : result
            ? "Open your new course"
            : "Create course"}
      </ActionButton>
      <dialog
        ref={dialog}
        className={`${styles.dialog} ${shared.workspace}`}
        aria-labelledby={headingId}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
        onClose={() => setOpen(false)}
      >
        <form onSubmit={(event) => void submit(event)}>
          <header className={styles.header}>
            <div className={styles.symbol} aria-hidden="true">
              <LearningSymbol kind="course" size={52} />
            </div>
            <button
              className={styles.close}
              type="button"
              aria-label="Close course creation"
              onClick={close}
              disabled={state === "saving"}
            >
              <X size={21} />
            </button>
          </header>
          <span className={styles.eyebrow}>Your academy · New course</span>
          <h2 ref={heading} tabIndex={-1} id={headingId}>
            {result ? "Your course is saved" : "What will you teach?"}
          </h2>
          <p className={styles.intro}>
            {result
              ? "Open your course to continue where you left off."
              : "Start with a name. Add your modules, videos, and practice one step at a time."}
          </p>
          {result ? (
            <div className={styles.success} role="status">
              <CheckCircle2 size={22} aria-hidden="true" />
              <div>
                <strong>{result.program.title}</strong>
                <span>Saved · Version 1</span>
              </div>
            </div>
          ) : (
            <>
              <label className={styles.label} htmlFor={`${headingId}-title`}>
                Course name <span>Required</span>
              </label>
              <input
                ref={input}
                id={`${headingId}-title`}
                className={styles.input}
                type="text"
                autoComplete="off"
                maxLength={200}
                required
                aria-describedby={helpId}
                placeholder="e.g. Confident sales conversations"
                value={title}
                disabled={!!intent}
                onChange={(event) => {
                  setTitle(event.target.value);
                  setMessage("");
                  setState("idle");
                }}
              />
              <p id={helpId} className={styles.note}>
                Your draft stays out of the learner catalog until it’s reviewed
                and published.
              </p>
            </>
          )}
          <div className={styles.status} role="status" aria-live="polite">
            {state === "saving"
              ? "Creating your course…"
              : message ||
                (intent
                  ? "A previous save needs confirmation. Check the same request before creating another course."
                  : "")}
          </div>
          <footer className={styles.footer}>
            {result ? (
              <Link
                className={styles.continue}
                href={`/studio/programs/${result.program.id}`}
              >
                {result.program.versions.find(
                  (version) => version.id === result.resource_id,
                )?.modules.length === 0
                  ? "Add your first module"
                  : "Open course"}{" "}
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
            ) : (
              <ActionButton
                type="submit"
                disabled={state === "saving" || (!intent && !title.trim())}
              >
                {state === "saving" ? (
                  <LoaderCircle
                    className={shared.revisionSpinner}
                    size={18}
                    aria-hidden="true"
                  />
                ) : null}
                {state === "saving"
                  ? "Creating course…"
                  : intent
                    ? "Check saved course"
                    : "Create draft"}
              </ActionButton>
            )}
            <ActionButton
              type="button"
              variant="quiet"
              onClick={close}
              disabled={state === "saving"}
            >
              {intent ? "Close for now" : "Close"}
            </ActionButton>
          </footer>
        </form>
      </dialog>
    </div>
  );
}
