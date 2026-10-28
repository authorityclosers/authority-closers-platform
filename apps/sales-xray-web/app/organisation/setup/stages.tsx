"use client";
import {
  ArrowDown,
  ArrowUp,
  Building2,
  ChevronRight,
  Pencil,
} from "lucide-react";
import { useEffect, useState } from "react";
import { notify } from "../../notice-center";
import { Button, Segmented, Skeleton } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import { JourneyTab } from "../../leads/journey/journey-view";
import { TemplateBuilder } from "../../leads/journey/builder";
import { AdPlatforms } from "../../leads/journey/ad-platforms";
import {
  drafts,
  move,
  problem,
  readJourney,
  readPipelines,
  readTemplates,
  saveJourney,
  type Draft,
  type JourneyView,
  type PipelinesView,
  type TemplateView,
} from "../../leads/journey/journey-client";
import styles from "./setup.module.css";

/** Saved stages first. Help never stands between the owner and a stage's controls. */
export function OrganisationStages() {
  const [view, setView] = useState<JourneyView | null>(null);
  const [list, setList] = useState<Draft[]>([]);
  const [pipes, setPipes] = useState<PipelinesView | null>(null);
  const [templates, setTemplates] = useState<TemplateView[] | null>(null);
  const [pipeline, setPipeline] = useState(() =>
    typeof window === "undefined"
      ? "main"
      : (new URLSearchParams(window.location.search).get("pipeline") ?? "main"),
  );
  const [part, setPart] = useState<"stages" | "ads">("stages");
  const [editing, setEditing] = useState<{ id: string; label: string } | null>(
    null,
  );
  const [advanced, setAdvanced] = useState(false);
  const [business, setBusiness] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fail = (reason: unknown, title: string) =>
    notify({
      id: "org-stage",
      tone: "error",
      title,
      message: reason instanceof Error ? reason.message : "Try again.",
    });
  const take = (next: JourneyView) => {
    setView(next);
    setList(drafts(next));
    setDirty(false);
  };
  useEffect(() => {
    let live = true;
    readPipelines().then(
      (next) => {
        if (live) setPipes(next);
      },
      () => undefined,
    );
    readTemplates().then(
      (next) => {
        if (live) setTemplates(next);
      },
      () => {
        if (live) setTemplates([]);
      },
    );
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    readJourney(pipeline).then(
      (next) => {
        if (live) {
          take(next);
          setError(null);
        }
      },
      (reason) => {
        if (live) {
          setError("Stages didn't load.");
          fail(reason, "Stages didn't load");
        }
      },
    );
    return () => {
      live = false;
    };
  }, [pipeline, attempt]);
  const choosePipeline = (next: string) => {
    if (dirty) {
      notify({
        id: "stage-draft",
        tone: "info",
        title: "Save or discard your stage changes first",
      });
      return;
    }
    setPipeline(next);
    setView(null);
    const url = new URL(window.location.href);
    url.searchParams.set("pipeline", next);
    window.history.replaceState(window.history.state, "", url);
  };
  if (!view)
    return (
      <div className={styles.stack}>
        {error ? (
          <button
            className={styles.button}
            onClick={() => setAttempt((value) => value + 1)}
          >
            Try loading stages again
          </button>
        ) : (
          <div aria-busy="true" aria-label="Loading lead stages">
            <Skeleton height={80} />
            <Skeleton height={240} />
          </div>
        )}
      </div>
    );
  if (view.version === 0) return <JourneyTab canManage={view.canEdit} />;
  const save = async () => {
    const issue = problem(list);
    if (issue) {
      setError(issue);
      return;
    }
    setBusy(true);
    try {
      take(await saveJourney(view.version, list, pipeline));
      notify({ id: "org-stage", tone: "success", title: "Lead stages saved" });
      setError(null);
    } catch (reason) {
      fail(reason, "Stages were not saved");
    } finally {
      setBusy(false);
    }
  };
  if (business)
    return (
      <TemplateBuilder
        view={view}
        templates={templates}
        first={false}
        iconFor={() => Building2}
        onCancel={() => setBusiness(false)}
        onSaved={(next) => {
          take(next);
          setBusiness(false);
        }}
        onFailed={fail}
      />
    );
  const active = list.filter((stage) => !stage.archived);
  const profile =
    templates?.find((item) => item.id === view.industry)?.name ??
    "Custom stages";
  return (
    <div className={styles.stack}>
      <header className={styles.head}>
        <div>
          <h2>Lead stages</h2>
          <p>Tap a stage to edit. Save when you’re ready.</p>
        </div>
      </header>
      <div className={styles.tools}>
        {pipes && pipes.pipelines.length > 1 ? (
          <label className={styles.copy}>
            Pipeline
            <select
              className={styles.search}
              value={pipeline}
              onChange={(event) => choosePipeline(event.target.value)}
            >
              {pipes.pipelines.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button
          className={styles.button}
          disabled={busy || dirty || !view.canEdit}
          onClick={() => setBusiness(true)}
        >
          <Building2 size={16} />
          {profile}
          <ChevronRight size={16} />
        </button>
      </div>
      <Segmented
        label="Stage setup"
        value={part}
        onChange={setPart}
        items={[
          { key: "stages", label: "Stages" },
          { key: "ads", label: "Ad platforms" },
        ]}
      />
      {part === "ads" ? (
        pipeline === "main" ? (
          <AdPlatforms version={view.version} />
        ) : (
          <p className={styles.help}>
            Ad platforms use the main pipeline’s stages.
          </p>
        )
      ) : (
        <ol className={styles.list} aria-label="Your lead stages">
          {active.map((stage, index) => (
            <li className={styles.stageCard} key={stage.id}>
              <span className={styles.number} aria-hidden="true">
                {index + 1}
              </span>
              <button
                className={styles.stageEdit}
                disabled={!view.canEdit || busy}
                onClick={() => setEditing({ id: stage.id, label: stage.label })}
                title={stage.label}
              >
                <span className={styles.copy}>
                  <strong>{stage.label}</strong>
                  <small>
                    {stage.kindWords ||
                      view.kinds[stage.kind ?? ""] ||
                      "Lead stage"}{" "}
                    · {stage.leads} {stage.leads === 1 ? "lead" : "leads"}
                  </small>
                </span>
                <Pencil size={16} aria-hidden="true" />
              </button>
              {view.canEdit ? (
                <span className={styles.stageMoves}>
                  <button
                    className={styles.button}
                    aria-label={`Move ${stage.label} earlier`}
                    disabled={busy || move(list, stage.id, -1) === list}
                    onClick={() => {
                      setList(move(list, stage.id, -1));
                      setDirty(true);
                    }}
                  >
                    <ArrowUp size={16} aria-hidden="true" />
                  </button>
                  <button
                    className={styles.button}
                    aria-label={`Move ${stage.label} later`}
                    disabled={busy || move(list, stage.id, 1) === list}
                    onClick={() => {
                      setList(move(list, stage.id, 1));
                      setDirty(true);
                    }}
                  >
                    <ArrowDown size={16} aria-hidden="true" />
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {dirty ? (
        <div className={styles.footer}>
          <button
            className={styles.button}
            disabled={busy}
            onClick={() => {
              take(view);
              setError(null);
            }}
          >
            Discard changes
          </button>
          <button
            className={styles.primary}
            disabled={busy}
            onClick={() => void save()}
          >
            Save stages
          </button>
        </div>
      ) : null}
      {error ? (
        <p role="status" className={styles.help}>
          {error}
        </p>
      ) : null}
      <details
        className={styles.details}
        onToggle={(event) => setAdvanced(event.currentTarget.open)}
      >
        <summary>More stage options</summary>
        {advanced ? (
          <div>
            <JourneyTab canManage={view.canEdit} />
          </div>
        ) : null}
      </details>
      <Sheet
        open={editing !== null}
        onClose={() => setEditing(null)}
        title="Stage name"
        footer={
          <Button
            variant="primary"
            disabled={
              !editing?.label.trim() || editing.label.trim().length > 40
            }
            onClick={() => {
              if (!editing) return;
              setList((current) =>
                current.map((stage) =>
                  stage.id === editing.id
                    ? { ...stage, label: editing.label.trim() }
                    : stage,
                ),
              );
              setDirty(true);
              setEditing(null);
            }}
          >
            Apply name
          </Button>
        }
      >
        <label className={styles.copy}>
          Name
          <input
            className={styles.search}
            maxLength={40}
            value={editing?.label ?? ""}
            onChange={(event) =>
              setEditing((current) =>
                current ? { ...current, label: event.target.value } : null,
              )
            }
          />
        </label>
        <p className={styles.help}>The stage’s meaning stays the same.</p>
      </Sheet>
    </div>
  );
}
