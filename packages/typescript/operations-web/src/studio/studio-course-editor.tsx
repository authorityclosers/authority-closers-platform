"use client";

import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import { ActionButton, LearningSymbol } from "@ac/ui";
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChevronRight,
  Eye,
  Layers,
  LockKeyhole,
  Pencil,
  Plus,
  Save,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import {
  AdminApiProblem,
  appendStudioActivity,
  appendStudioModule,
  loadStudioProgram,
  newIdempotencyKey,
  updateStudioActivity,
  updateStudioModule,
  type StudioActivityKind,
  type StudioDraftMutationResponse,
  type StudioProgramDetail,
} from "../admin-api";
import styles from "./studio-course-editor.module.css";
import {
  StudioLessonTypePicker,
  studioLessonKinds as kinds,
} from "./studio-lesson-type-picker";
import { StudioRevisionAction } from "./studio-revision-action";
import { StudioVideoUpload } from "./studio-video-upload";
import { StudioLessonVideoPreview } from "./studio-lesson-video-preview";
import {
  StudioVideoPanel,
  readStudioVideoRecoveryActivity,
} from "./studio-video-panel";
import {
  clearStudioDraft,
  readStudioDraft,
  readStudioPublication,
  readStudioRevision,
  retainStudioDraft,
  type StudioSelection as Selection,
  type StudioFields as Fields,
  type StudioDraftCommand as Command,
} from "./studio-draft-recovery";

type Version = StudioProgramDetail["versions"][number];
type SaveState =
  | "idle"
  | "saving"
  | "saved"
  | "unknown"
  | "conflict"
  | "comparing"
  | "denied"
  | "error";

const emptyFields: Fields = {
  title: "",
  prompt: "",
  kind: "REFLECTION",
  isRequired: true,
};
const sameFields = (a: Fields, b: Fields) =>
  a.title === b.title &&
  a.prompt === b.prompt &&
  a.kind === b.kind &&
  a.isRequired === b.isRequired;
const isNew = (selection: Selection) => selection.type.startsWith("new-");
const isActivity = (selection: Selection) =>
  selection.type.endsWith("activity");

function initialSelection(version: Version): Selection {
  const courseModule = version.modules[0];
  const activity = courseModule?.activities[0];
  return activity
    ? { type: "activity", moduleId: courseModule.id, activityId: activity.id }
    : courseModule
      ? { type: "module", moduleId: courseModule.id }
      : { type: "new-module", moduleId: "" };
}

function fieldsFor(version: Version, selection: Selection): Fields | null {
  if (isNew(selection)) return emptyFields;
  const courseModule = version.modules.find(
    (item) => item.id === selection.moduleId,
  );
  if (!courseModule) return null;
  if (selection.type === "module")
    return { ...emptyFields, title: courseModule.title };
  const activity = courseModule.activities.find(
    (item) => item.id === selection.activityId,
  );
  if (!activity || !(activity.kind in kinds)) return null;
  return {
    title: activity.title,
    prompt: activity.prompt ?? "",
    kind: activity.kind as StudioActivityKind,
    isRequired: activity.is_required,
  };
}

async function sendCommand(
  command: Command,
): Promise<StudioDraftMutationResponse> {
  const common = {
    programVersionId: command.versionId,
    title: command.fields.title.trim(),
    ifMatch: command.ifMatch,
    idempotencyKey: command.idempotencyKey,
  };
  const { selection, fields } = command;
  if (selection.type === "new-module") return appendStudioModule(common);
  if (selection.type === "module")
    return updateStudioModule({ ...common, moduleId: selection.moduleId });
  const activity = { ...common, prompt: fields.prompt.trim() || null };
  if (selection.type === "new-activity")
    return appendStudioActivity({
      ...activity,
      moduleId: selection.moduleId,
      kind: fields.kind,
      isRequired: fields.isRequired,
    });
  return updateStudioActivity({
    ...activity,
    activityId: selection.activityId!,
  });
}

export function StudioCourseEditor({
  initialProgram,
  canWrite,
  renderPublication,
  recoveryContext = "",
  videoRecoveryContext = recoveryContext,
}: {
  initialProgram: StudioProgramDetail;
  canWrite: boolean;
  recoveryContext?: string;
  videoRecoveryContext?: string;
  renderPublication: (
    version: Version | undefined,
    refresh: () => void,
    setPending: (pending: boolean) => void,
  ) => ReactNode;
}) {
  // Parent mounts only after the real, current, authorized course read.
  const [recovery] = useState(() =>
    readStudioDraft(recoveryContext, initialProgram.id),
  );
  const [publicationRecovery] = useState(() =>
    readStudioPublication(recoveryContext, initialProgram.id),
  );
  const [revisionRecovery] = useState(() =>
    readStudioRevision(recoveryContext, initialProgram.id),
  );
  const [program, setProgram] = useState(initialProgram);
  const [videoRecoveryActivity] = useState(() =>
    readStudioVideoRecoveryActivity(videoRecoveryContext, initialProgram.id),
  );
  const videoRecoveryVersion = initialProgram.versions.find((item) =>
    item.modules.some((module) =>
      module.activities.some(
        (activity) => activity.id === videoRecoveryActivity,
      ),
    ),
  );
  const videoRecoveryModule = videoRecoveryVersion?.modules.find((module) =>
    module.activities.some((activity) => activity.id === videoRecoveryActivity),
  );
  const videoSelection: Selection | null =
    videoRecoveryActivity && videoRecoveryModule
      ? {
          type: "activity",
          moduleId: videoRecoveryModule.id,
          activityId: videoRecoveryActivity,
        }
      : null;
  const recoveredVersionId =
    publicationRecovery?.programVersionId ??
    revisionRecovery?.programVersionId ??
    recovery?.versionId ??
    videoRecoveryVersion?.id;
  const initialVersion = recoveredVersionId
    ? initialProgram.versions.find((item) => item.id === recoveredVersionId)
    : (initialProgram.versions.find((item) => item.status === "draft") ??
      initialProgram.versions[0]);
  const [versionId, setVersionId] = useState(
    publicationRecovery?.programVersionId ??
      revisionRecovery?.programVersionId ??
      recovery?.versionId ??
      initialVersion?.id ??
      "",
  );
  const version = program.versions.find((item) => item.id === versionId);
  const [selection, setSelection] = useState<Selection>(
    () =>
      recovery?.selection ??
      videoSelection ??
      (initialVersion
        ? initialSelection(initialVersion)
        : { type: "new-module", moduleId: "" }),
  );
  const [fields, setFields] = useState<Fields>(
    () =>
      recovery?.fields ??
      (initialVersion
        ? (fieldsFor(
            initialVersion,
            videoSelection ?? initialSelection(initialVersion),
          ) ?? emptyFields)
        : emptyFields),
  );
  const [baseline, setBaseline] = useState(recovery?.baseline ?? fields);
  const [tab, setTab] = useState<"edit" | "preview" | "publication">(
    publicationRecovery ? "publication" : "edit",
  );
  const [saveState, setSaveState] = useState<SaveState>(() =>
    !recovery
      ? "idle"
      : !canWrite || recovery.state === "denied"
        ? "denied"
        : recovery.pending
          ? "unknown"
          : recovery.state === "conflict" || version?.etag !== recovery.etag
            ? "conflict"
            : "idle",
  );
  const [message, setMessage] = useState(
    recovery
      ? recovery.pending
        ? "Your unconfirmed save was recovered in this tab. Check the same save before making another change."
        : "Your unsaved edits were recovered in this tab. Compare the latest draft if it changed while you were away."
      : "",
  );
  const [comparison, setComparison] = useState<Fields | null>(null);
  const [publicationPending, setPublicationPending] = useState(
    Boolean(publicationRecovery),
  );
  const [revisionPending, setRevisionPending] = useState(
    Boolean(revisionRecovery),
  );
  const [videoPending, setVideoPending] = useState(false);
  const [uploadPending, setUploadPending] = useState(false);
  const [videoLibraryRevision, setVideoLibraryRevision] = useState(0);
  const [leave, setLeave] = useState<(() => void) | null>(null);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const pending = useRef<Command | null>(recovery?.pending ?? null);
  const [refreshRequest, setRefreshRequest] = useState(0);
  const bypassLeave = useRef(false);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const latestFields = useRef(fields);
  useLayoutEffect(() => {
    latestFields.current = fields;
  }, [fields]);
  const revision = useRef(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const editorHeading = useRef<HTMLHeadingElement>(null);
  const dirty = !sameFields(fields, baseline);
  const hasPending = saveState === "saving" || saveState === "unknown";
  const unsettled =
    saveState === "saving" ||
    saveState === "unknown" ||
    saveState === "comparing" ||
    publicationPending ||
    revisionPending ||
    videoPending ||
    uploadPending;
  const writable =
    canWrite &&
    program.access === "selected_tenant" &&
    version?.status === "draft" &&
    Boolean(version.etag) &&
    saveState !== "denied" &&
    !publicationPending &&
    !revisionPending &&
    !videoPending;
  const canReplay =
    canWrite &&
    program.access === "selected_tenant" &&
    hasPending &&
    !publicationPending &&
    !revisionPending &&
    !videoPending;
  const selectedModule = version?.modules.find(
    (item) => item.id === selection.moduleId,
  );
  const saveHint =
    message ||
    (isNew(selection) && !fields.title.trim()
      ? `Add a title to create this ${isActivity(selection) ? "lesson" : "module"}.`
      : dirty
        ? "Unsaved changes"
        : version?.status === "draft"
          ? "All changes saved in this draft"
          : "Published content · read only");

  function editFields(next: Fields) {
    setFields(next);
    // New typing after a confirmed save must not keep announcing "Saved".
    // In-flight, uncertain and conflict messages remain until their own recovery.
    if (saveState === "idle" || saveState === "saved") {
      setSaveState("idle");
      setMessage("");
    }
  }

  useLayoutEffect(() => {
    if (bypassLeave.current) return;
    if (dirty || pending.current) {
      retainStudioDraft(recoveryContext, program.id, {
        versionId,
        selection,
        fields,
        baseline,
        etag: version?.etag ?? null,
        pending: pending.current,
        state: pending.current
          ? "unknown"
          : saveState === "denied"
            ? "denied"
            : saveState === "conflict"
              ? "conflict"
              : "dirty",
      });
    } else clearStudioDraft(recoveryContext, program.id);
  }, [
    recoveryContext,
    program.id,
    versionId,
    selection,
    fields,
    baseline,
    version?.etag,
    dirty,
    saveState,
  ]);

  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty && !unsettled) return;
    const unload = (event: BeforeUnloadEvent) => {
      if (bypassLeave.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const anchor = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const target =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !(target instanceof HTMLAnchorElement) ||
        target.target === "_blank" ||
        target.hasAttribute("download") ||
        target.origin !== window.location.origin ||
        target.href === window.location.href
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      setLeave(() => () => window.location.assign(target.href));
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", anchor, true);
    return () => {
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", anchor, true);
    };
  }, [dirty, unsettled]);
  useEffect(() => {
    if (leave) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [leave]);

  function navigate(action: () => void) {
    if (dirty || unsettled) setLeave(() => action);
    else action();
  }
  function select(next: Selection, nextVersion = version) {
    if (!nextVersion) return;
    setOutlineOpen(false);
    revision.current += 1;
    bypassLeave.current = false;
    clearStudioDraft(recoveryContext, program.id);
    setSelection(next);
    setFields(fieldsFor(nextVersion, next) ?? emptyFields);
    setBaseline(fieldsFor(nextVersion, next) ?? emptyFields);
    setComparison(null);
    setSaveState("idle");
    setMessage("");
    pending.current = null;
    setTab("edit");
    requestAnimationFrame(() => editorHeading.current?.focus());
  }
  function assertProgram(next: StudioProgramDetail) {
    if (
      next.id !== initialProgram.id ||
      next.tenant_id !== initialProgram.tenant_id
    )
      throw new Error("Unexpected Studio context");
    return next;
  }
  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (
      (!writable && !canReplay) ||
      inFlight.current ||
      (!pending.current && !version?.etag) ||
      saveState === "conflict" ||
      (!pending.current && !fields.title.trim())
    )
      return;
    const command = pending.current ?? {
      selection: { ...selection },
      fields: { ...fields },
      versionId: version!.id,
      ifMatch: version!.etag!,
      idempotencyKey: newIdempotencyKey(),
    };
    revision.current += 1;
    pending.current = command;
    inFlight.current = true;
    setSaveState("saving");
    setMessage("Saving your draft…");
    try {
      const result = await sendCommand(command);
      if (!mounted.current) return;
      const next = assertProgram(result.program);
      const nextVersion = next.versions.find(
        (item) => item.id === command.versionId,
      );
      const nextSelection: Selection =
        command.selection.type === "new-module"
          ? { type: "module", moduleId: result.resource_id }
          : command.selection.type === "new-activity"
            ? {
                type: "activity",
                moduleId: command.selection.moduleId,
                activityId: result.resource_id,
              }
            : command.selection;
      const confirmed = nextVersion
        ? fieldsFor(nextVersion, nextSelection)
        : null;
      if (!nextVersion || !confirmed)
        throw new Error("Saved content could not be reconciled");
      setProgram(next);
      setSelection(nextSelection);
      setBaseline(confirmed);
      pending.current = null;
      const submitted = {
        ...command.fields,
        title: command.fields.title.trim(),
        prompt: command.fields.prompt.trim(),
      };
      if (!sameFields(confirmed, submitted)) {
        setComparison(confirmed);
        setSaveState("conflict");
        setMessage(
          "Your earlier save was recorded, but this content has changed since. Compare the latest draft before saving again.",
        );
      } else {
        const unchangedSinceSend = sameFields(
          latestFields.current,
          command.fields,
        );
        if (unchangedSinceSend) setFields(confirmed);
        setSaveState("saved");
        setComparison(null);
        setMessage(
          unchangedSinceSend
            ? "Saved to draft. Learners still see the published version."
            : "Previous changes saved. Your newer changes still need saving.",
        );
      }
    } catch (error) {
      if (!mounted.current) return;
      if (
        error instanceof AdminApiProblem &&
        error.status >= 400 &&
        error.status < 500
      ) {
        pending.current = null;
        if (error.status === 412 || error.status === 409) {
          setSaveState("conflict");
          setMessage(
            "The draft changed before this save. Your edits are still here. Load the latest draft to compare.",
          );
        } else if ([401, 403, 404, 410].includes(error.status)) {
          setSaveState("denied");
          setMessage(
            "Editing access is no longer available. Your unsaved text is still here to copy. Sign in again to check your access.",
          );
        } else {
          setSaveState("error");
          setMessage(
            "This change could not be saved. Check the title and instructions, then try again.",
          );
        }
      } else {
        setSaveState("unknown");
        setMessage(
          "We couldn’t confirm the save. Keep this page open and check the same save before making another one.",
        );
      }
    } finally {
      inFlight.current = false;
    }
  }
  async function compareLatest() {
    if (inFlight.current || pending.current) return;
    revision.current += 1;
    inFlight.current = true;
    setSaveState("comparing");
    try {
      const next = assertProgram(await loadStudioProgram(program.id));
      if (!mounted.current) return;
      const nextVersion = next.versions.find((item) => item.id === versionId);
      const current = nextVersion ? fieldsFor(nextVersion, selection) : null;
      setProgram(next);
      if (!current || nextVersion?.status !== "draft") {
        setSaveState("denied");
        setMessage(
          "This version can no longer be edited. Your unsaved text is preserved below.",
        );
        return;
      }
      setComparison(current);
      setSaveState("conflict");
      setMessage(
        "Compare the latest saved content with your edits below. Nothing has been overwritten.",
      );
    } catch (error) {
      if (!mounted.current) return;
      setSaveState(
        error instanceof AdminApiProblem &&
          [401, 403, 404].includes(error.status)
          ? "denied"
          : "conflict",
      );
      setMessage(
        "The latest draft could not be loaded. Your edits remain unchanged.",
      );
    } finally {
      inFlight.current = false;
    }
  }
  const refresh = useEffectEvent(async () => {
    if (
      dirty ||
      pending.current ||
      inFlight.current ||
      revisionPending ||
      videoPending
    )
      return;
    const currentRevision = ++revision.current;
    const currentFields = latestFields.current;
    try {
      const next = assertProgram(await loadStudioProgram(program.id));
      if (
        mounted.current &&
        revision.current === currentRevision &&
        !pending.current &&
        !inFlight.current &&
        sameFields(currentFields, latestFields.current)
      )
        setProgram(next);
    } catch {
      if (
        mounted.current &&
        revision.current === currentRevision &&
        !pending.current &&
        !inFlight.current
      ) {
        setSaveState("error");
        setMessage(
          "The current course could not be refreshed. Try opening it again.",
        );
      }
    }
  });
  useEffect(() => {
    if (!refreshRequest) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void refresh();
    });
    return () => {
      active = false;
    };
  }, [refreshRequest]);

  return (
    <div className={styles.workspace} data-studio-editor="course">
      <header className={styles.header}>
        <Link href="/studio/programs" className={styles.back}>
          <ArrowLeft size={16} aria-hidden="true" />
          All courses
        </Link>
        <div className={styles.titleRow}>
          <div>
            <span className={styles.eyebrow}>Course workspace</span>
            <h2>{program.title}</h2>
          </div>
          <label className={styles.versionControl}>
            <span>Version</span>
            <select
              aria-label="Course version"
              value={versionId}
              disabled={unsettled}
              onChange={(event) => {
                const id = event.target.value;
                navigate(() => {
                  const next = program.versions.find((v) => v.id === id);
                  if (next) {
                    setVersionId(id);
                    select(initialSelection(next), next);
                  }
                });
              }}
            >
              {program.versions.map((item) => (
                <option value={item.id} key={item.id}>
                  v{item.version_number} · {item.status}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className={styles.toolbar}>
          <span className={styles.badge}>
            {version?.status === "draft" ? (
              <Pencil size={14} />
            ) : (
              <LockKeyhole size={14} />
            )}{" "}
            {version?.status === "draft"
              ? "Draft · not visible to learners"
              : "Published history · read only"}
          </span>
          <div className={styles.tabs} role="group" aria-label="Workspace view">
            {(
              [
                ["edit", Pencil, "Content"],
                ["preview", Eye, "Preview"],
                ["publication", ShieldCheck, "Publication"],
              ] as const
            ).map(([id, Icon, label]) => (
              <button
                key={id}
                type="button"
                aria-pressed={tab === id}
                disabled={publicationPending || revisionPending || videoPending}
                onClick={() => setTab(id)}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
      </header>
      <StudioVideoUpload
        programId={program.id}
        recoveryContext={videoRecoveryContext}
        canWrite={canWrite && program.access === "selected_tenant"}
        disabled={publicationPending || revisionPending || videoPending}
        onPendingChange={setUploadPending}
        onReady={() => setVideoLibraryRevision((value) => value + 1)}
      />
      <StudioRevisionAction
        key={`${recoveryContext}:${program.id}:${versionId}`}
        program={program}
        source={version}
        canWrite={canWrite}
        disabled={dirty || unsettled}
        recoveryContext={recoveryContext}
        onPendingChange={(value) => {
          revision.current += 1;
          setRevisionPending(value);
        }}
        onOpenVersion={(nextVersion) =>
          navigate(() => {
            setVersionId(nextVersion.id);
            select(initialSelection(nextVersion), nextVersion);
          })
        }
        onCreated={(nextProgram, createdId) => {
          const next = assertProgram(nextProgram);
          const createdVersion = next.versions.find(
            (item) => item.id === createdId,
          );
          if (!createdVersion)
            throw new Error("The created revision was not returned");
          setProgram(next);
          setVersionId(createdId);
          select(initialSelection(createdVersion), createdVersion);
          setMessage(
            createdVersion.status === "draft"
              ? "Draft revision created. Review the copied content and connect its media before publication."
              : "Your earlier revision was found. This version is now read only.",
          );
        }}
      />
      {!version ? (
        <div className={styles.empty}>
          <Layers />
          {publicationRecovery ? (
            renderPublication(
              undefined,
              () => setRefreshRequest((current) => current + 1),
              setPublicationPending,
            )
          ) : recovery ? (
            <>
              <h3>Recovered edits</h3>
              <p>
                This version is not in the current course history. Your text is
                available to copy; only an existing unconfirmed command can be
                checked.
              </p>
              <label className={styles.field}>
                Recovered title
                <input readOnly value={fields.title} />
              </label>
              <label className={styles.field}>
                Recovered instructions
                <textarea readOnly value={fields.prompt} />
              </label>
              {hasPending ? (
                <ActionButton
                  disabled={!canReplay || saveState === "saving"}
                  onClick={() => {
                    void save();
                  }}
                >
                  {saveState === "saving" ? "Checking save…" : "Check save"}
                </ActionButton>
              ) : null}
            </>
          ) : (
            <>
              <h3>No course version yet</h3>
              <p>
                A draft version needs to be created before you can add content.
              </p>
            </>
          )}
        </div>
      ) : (
        <div className={styles.layout}>
          <button
            type="button"
            className={styles.outlineToggle}
            aria-expanded={outlineOpen}
            aria-controls="course-outline"
            onClick={() => setOutlineOpen((current) => !current)}
          >
            <Layers size={18} aria-hidden="true" />
            Course outline · {version.modules.length} modules
            <ChevronRight size={16} aria-hidden="true" />
          </button>
          <aside
            id="course-outline"
            className={styles.outline}
            data-expanded={outlineOpen}
            aria-label="Course outline"
          >
            <div className={styles.outlineHeading}>
              <h3>Course outline</h3>
              <span>{version.modules.length} modules</span>
            </div>
            {version.modules.map((module) => (
              <div className={styles.module} key={module.id}>
                <button
                  type="button"
                  className={styles.moduleButton}
                  aria-current={
                    selection.type === "module" &&
                    selection.moduleId === module.id
                      ? "true"
                      : undefined
                  }
                  disabled={unsettled}
                  onClick={() =>
                    navigate(() =>
                      select({ type: "module", moduleId: module.id }),
                    )
                  }
                >
                  <span className={styles.moduleNumber}>
                    {String(module.position).padStart(2, "0")}
                  </span>
                  <span>{module.title}</span>
                </button>
                <ol>
                  {module.activities.map((activity) => (
                    <li key={activity.id}>
                      <button
                        type="button"
                        aria-current={
                          selection.activityId === activity.id
                            ? "true"
                            : undefined
                        }
                        disabled={unsettled}
                        onClick={() =>
                          navigate(() =>
                            select({
                              type: "activity",
                              moduleId: module.id,
                              activityId: activity.id,
                            }),
                          )
                        }
                      >
                        <LearningSymbol
                          kind={
                            kinds[activity.kind as StudioActivityKind]
                              ?.symbol ?? "reflect"
                          }
                          size={24}
                        />
                        <span>
                          {activity.title}
                          <small>
                            {kinds[activity.kind as StudioActivityKind]
                              ?.label ?? "Activity"}
                          </small>
                        </span>
                        <ChevronRight size={14} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ol>
                {writable ? (
                  <button
                    className={styles.add}
                    type="button"
                    disabled={unsettled}
                    onClick={() =>
                      navigate(() =>
                        select({ type: "new-activity", moduleId: module.id }),
                      )
                    }
                  >
                    <Plus size={15} aria-hidden="true" />
                    Add lesson
                    <span className={styles.srOnly}> to {module.title}</span>
                  </button>
                ) : null}
              </div>
            ))}
            {writable ? (
              <ActionButton
                variant="secondary"
                disabled={unsettled}
                onClick={() =>
                  navigate(() => select({ type: "new-module", moduleId: "" }))
                }
              >
                <Plus size={16} aria-hidden="true" />
                Add module
              </ActionButton>
            ) : null}
            <p className={styles.outlineNote}>
              <LockKeyhole size={14} aria-hidden="true" />
              Published versions stay unchanged while you work.
            </p>
          </aside>
          <section className={styles.content} aria-label="Selected content">
            {tab === "publication" ? (
              <div className={styles.review}>
                <span className={styles.eyebrow}>Review & release</span>
                <h3>Ready when the content is.</h3>
                <p>
                  Saving and publishing are separate. A content review must
                  match this exact version before it can go live.
                </p>
                {dirty ||
                saveState === "saving" ||
                saveState === "unknown" ||
                saveState === "comparing" ? (
                  <div className={styles.notice}>
                    <TriangleAlert size={20} />
                    <p>
                      Save or resolve your current edits before reviewing
                      publication.
                    </p>
                  </div>
                ) : (
                  <>
                    {renderPublication(
                      version,
                      () => {
                        setRefreshRequest((current) => current + 1);
                      },
                      setPublicationPending,
                    )}
                  </>
                )}
                <h4>Publication checklist</h4>
                {version.blockers.length ? (
                  <ul className={styles.checklist}>
                    {version.blockers.map((blocker) => (
                      <li key={blocker}>
                        <TriangleAlert size={17} aria-hidden="true" />
                        {(
                          {
                            provenance_incomplete:
                              "Record the source and a complete content review.",
                            content_digest_mismatch:
                              "Review the latest content after the edits.",
                            structure_invalid:
                              "Check the module order and required learning activities.",
                            supersession_required:
                              "Choose which published version this draft replaces.",
                            version_not_draft:
                              "This version is already immutable.",
                          } as Record<string, string>
                        )[blocker] ??
                          "This version needs an additional publication check."}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.notice}>
                    <Check size={18} />
                    No publication blockers reported.
                  </p>
                )}
                <details className={styles.provenance}>
                  <summary>Source & review details</summary>
                  <dl>
                    {[
                      ["Source", version.content_source_ref],
                      ["Reviewer", version.content_reviewed_by],
                      ["Reviewed at", version.content_reviewed_at],
                      ["Release", version.release_id],
                      ["Content digest", version.content_digest],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value ?? "Not recorded"}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </div>
            ) : tab === "preview" ? (
              <div className={styles.preview}>
                <div className={styles.previewNote}>
                  <Eye size={16} />
                  {dirty
                    ? "Previewing your unsaved edits"
                    : "Content preview"}{" "}
                  · no learner progress is recorded
                </div>
                <LearningSymbol
                  kind={
                    isActivity(selection) ? kinds[fields.kind].symbol : "course"
                  }
                  size={64}
                />
                <span className={styles.eyebrow}>
                  {isActivity(selection) ? kinds[fields.kind].label : "Module"}
                </span>
                <h3>{fields.title || "Your title goes here"}</h3>
                <p className={styles.previewPrompt}>
                  {fields.prompt ||
                    (isActivity(selection)
                      ? "Your instructions will appear here."
                      : "Select an activity in the outline to preview its content.")}
                </p>
                {selection.type === "activity" &&
                selection.activityId &&
                fields.kind === "VIDEO" ? (
                  <StudioLessonVideoPreview
                    programId={program.id}
                    activityId={selection.activityId}
                    versionStatus={version.status}
                    canWrite={canWrite && program.access === "selected_tenant"}
                    recoveryContext={videoRecoveryContext}
                  />
                ) : null}
                <ActionButton
                  variant="secondary"
                  onClick={() => setTab("edit")}
                >
                  <Pencil size={16} />
                  Back to content
                </ActionButton>
              </div>
            ) : (
              <>
                {selection.type === "activity" &&
                selection.activityId &&
                fields.kind === "VIDEO" ? (
                  <StudioVideoPanel
                    programId={program.id}
                    activityId={selection.activityId}
                    versionStatus={version.status}
                    canWrite={canWrite && program.access === "selected_tenant"}
                    recoveryContext={videoRecoveryContext}
                    libraryRevision={videoLibraryRevision}
                    onPendingChange={setVideoPending}
                  />
                ) : null}
                <form className={styles.editor} onSubmit={save}>
                  <div className={styles.editorHeading}>
                    <div>
                      <span className={styles.eyebrow}>
                        {selectedModule && isActivity(selection)
                          ? selectedModule.title
                          : "Course content"}
                      </span>
                      <h3 ref={editorHeading} tabIndex={-1}>
                        {isNew(selection)
                          ? `New ${isActivity(selection) ? "lesson" : "module"}`
                          : isActivity(selection)
                            ? "Lesson details"
                            : "Edit module"}
                      </h3>
                    </div>
                    {isActivity(selection) ? (
                      <LearningSymbol
                        kind={kinds[fields.kind].symbol}
                        size={48}
                      />
                    ) : (
                      <Layers size={28} aria-hidden="true" />
                    )}
                  </div>
                  {!writable ? (
                    <p className={styles.notice}>
                      <LockKeyhole size={18} />
                      This content is read only.{" "}
                      {dirty
                        ? "Your unsaved edits are preserved for copying."
                        : "Editing requires access to a draft in your academy."}
                    </p>
                  ) : null}
                  {comparison ? (
                    <div className={styles.comparison}>
                      <span className={styles.eyebrow}>
                        Latest saved content
                      </span>
                      <h4>{comparison.title || "New content"}</h4>
                      <p>{comparison.prompt || "No instructions"}</p>
                      <div className={styles.comparisonActions}>
                        <ActionButton
                          variant="secondary"
                          disabled={!writable}
                          onClick={() => {
                            setBaseline(comparison);
                            setComparison(null);
                            setSaveState("idle");
                            setMessage(
                              "Latest version reviewed. Save your edits when ready.",
                            );
                          }}
                        >
                          Keep my edits
                        </ActionButton>
                        <ActionButton
                          variant="quiet"
                          onClick={() => {
                            setFields(comparison);
                            setBaseline(comparison);
                            setComparison(null);
                            setSaveState("idle");
                            setMessage("Latest saved content loaded.");
                          }}
                        >
                          Use latest saved content
                        </ActionButton>
                      </div>
                    </div>
                  ) : null}
                  {selection.type === "new-activity" ? (
                    <StudioLessonTypePicker
                      value={fields.kind}
                      disabled={!writable || unsettled}
                      onChange={(kind) => editFields({ ...fields, kind })}
                    />
                  ) : null}
                  <label className={styles.field}>
                    <span>
                      {isActivity(selection) ? "Lesson title" : "Module title"}
                      <small>Required</small>
                    </span>
                    <input
                      value={fields.title}
                      maxLength={isActivity(selection) ? 240 : 200}
                      required
                      readOnly={!writable}
                      onChange={(e) =>
                        editFields({ ...fields, title: e.target.value })
                      }
                      placeholder={
                        isActivity(selection)
                          ? "What will the learner work on?"
                          : "Give this module a clear purpose"
                      }
                    />
                    <small>
                      A short, clear title learners will see in their course.
                    </small>
                  </label>
                  {isActivity(selection) ? (
                    <>
                      <div className={styles.metadataRow}>
                        {selection.type !== "new-activity" ? (
                          <div className={styles.metadata}>
                            <span>Lesson format</span>
                            <strong>{kinds[fields.kind].label}</strong>
                          </div>
                        ) : null}
                        {selection.type === "new-activity" ? (
                          <label className={styles.checkbox}>
                            <input
                              type="checkbox"
                              checked={fields.isRequired}
                              disabled={!writable || unsettled}
                              onChange={(e) =>
                                editFields({
                                  ...fields,
                                  isRequired: e.target.checked,
                                })
                              }
                            />
                            <span>
                              Required to complete this course
                              <small>
                                Included in course completion requirements.
                              </small>
                            </span>
                          </label>
                        ) : (
                          <div className={styles.metadata}>
                            <span>Completion requirement</span>
                            <strong>
                              {fields.isRequired ? "Required" : "Optional"}
                            </strong>
                          </div>
                        )}
                      </div>
                      <label className={styles.field}>
                        <span>
                          Learner instructions <small>Optional</small>
                        </span>
                        <textarea
                          value={fields.prompt}
                          rows={9}
                          maxLength={2000}
                          readOnly={!writable}
                          onChange={(e) =>
                            editFields({ ...fields, prompt: e.target.value })
                          }
                          placeholder="Explain the task, what to consider, and what to do next."
                        />
                        <small className={styles.characterCount}>
                          {fields.prompt.length.toLocaleString()} / 2,000
                          characters · plain text
                        </small>
                      </label>
                    </>
                  ) : (
                    <>
                      <p className={styles.help}>
                        {isNew(selection)
                          ? "A module groups related lessons into one clear topic. Save its title, then add your first lesson."
                          : "Group related video lessons and practice activities here. You can update the module title without changing its lessons."}
                      </p>
                      {selection.type === "module" &&
                      selectedModule &&
                      writable &&
                      !dirty &&
                      !unsettled ? (
                        <div className={styles.nextStep}>
                          <LearningSymbol kind="watch" size={44} />
                          <div>
                            <h4>
                              {selectedModule.activities.length
                                ? "Keep building this module"
                                : "Your module is ready for its first lesson"}
                            </h4>
                            <p>
                              Choose a video, reflection or hands-on practice.
                            </p>
                            <ActionButton
                              type="button"
                              variant="secondary"
                              onClick={() =>
                                navigate(() =>
                                  select({
                                    type: "new-activity",
                                    moduleId: selectedModule.id,
                                  }),
                                )
                              }
                            >
                              <Plus size={16} aria-hidden="true" />
                              {selectedModule.activities.length
                                ? "Add another lesson"
                                : "Add your first lesson"}
                            </ActionButton>
                          </div>
                        </div>
                      ) : null}
                    </>
                  )}
                  <footer className={styles.saveBar}>
                    <div
                      role="status"
                      aria-live="polite"
                      className={styles.saveStatus}
                      data-state={saveState}
                    >
                      {saveState === "saved" && !dirty ? (
                        <Check size={18} />
                      ) : dirty ? (
                        <Pencil size={16} />
                      ) : (
                        <ShieldCheck size={17} />
                      )}
                      <span>{saveHint}</span>
                    </div>
                    {saveState === "conflict" && !comparison ? (
                      <ActionButton
                        variant="secondary"
                        onClick={() => {
                          void compareLatest();
                        }}
                      >
                        Compare latest draft
                      </ActionButton>
                    ) : (
                      <ActionButton
                        type="submit"
                        disabled={
                          (!writable && !canReplay) ||
                          (!dirty && saveState !== "unknown") ||
                          (unsettled && saveState !== "unknown") ||
                          saveState === "conflict" ||
                          (saveState !== "unknown" && !fields.title.trim())
                        }
                        formNoValidate={saveState === "unknown"}
                      >
                        <Save size={16} aria-hidden="true" />
                        {saveState === "saving"
                          ? "Saving…"
                          : saveState === "unknown"
                            ? "Check save"
                            : isNew(selection)
                              ? isActivity(selection)
                                ? "Create lesson"
                                : "Add module"
                              : "Save changes"}
                      </ActionButton>
                    )}
                  </footer>
                </form>
              </>
            )}
          </section>
        </div>
      )}
      <dialog
        ref={dialogRef}
        className={styles.leaveDialog}
        aria-labelledby="studio-leave-title"
        onCancel={() => setLeave(null)}
        onClose={() => setLeave(null)}
      >
        <TriangleAlert size={28} />
        <h3 id="studio-leave-title">
          {unsettled ? "Resolve your save first" : "Leave these edits?"}
        </h3>
        <p>
          {unsettled
            ? "A save has not been confirmed yet. Check its result here before leaving so you can safely recover it."
            : "Your unsaved edits will be discarded. The saved draft will stay unchanged."}
        </p>
        <ActionButton onClick={() => setLeave(null)}>Keep editing</ActionButton>
        {!unsettled ? (
          <ActionButton
            variant="secondary"
            onClick={() => {
              const action = leave;
              bypassLeave.current = true;
              clearStudioDraft(recoveryContext, program.id);
              setLeave(null);
              action?.();
            }}
          >
            Discard unsaved edits
          </ActionButton>
        ) : null}
      </dialog>
    </div>
  );
}
