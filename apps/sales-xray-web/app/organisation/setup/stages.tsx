"use client";
import { Building2, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { notify } from "../../notice-center";
import { Segmented, Skeleton } from "../../ui/kit";
import { JourneyTab } from "../../leads/journey/journey-view";
import { TemplateBuilder } from "../../leads/journey/builder";
import { AdPlatforms } from "../../leads/journey/ad-platforms";
import {
  readJourney,
  readPipelines,
  readTemplates,
  type JourneyView,
  type PipelinesView,
  type TemplateView,
} from "../../leads/journey/journey-client";
import { StageEditor } from "./stage-editor";
import styles from "./setup.module.css";

/** Saved stages first. Help never stands between the owner and a stage's controls.
 *  Every change saves at once (the stage editor, owner + Dipak, 30 Oct 2026). */
export function OrganisationStages() {
  const [view, setView] = useState<JourneyView | null>(null);
  const [pipes, setPipes] = useState<PipelinesView | null>(null);
  const [templates, setTemplates] = useState<TemplateView[] | null>(null);
  const [pipeline, setPipeline] = useState(() =>
    typeof window === "undefined"
      ? "main"
      : (new URLSearchParams(window.location.search).get("pipeline") ?? "main"),
  );
  const [part, setPart] = useState<"stages" | "ads">("stages");
  const [advanced, setAdvanced] = useState(false);
  const [business, setBusiness] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fail = (reason: unknown, title: string) =>
    notify({
      id: "org-stage",
      tone: "error",
      title,
      message: reason instanceof Error ? reason.message : "Try again.",
    });
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
          setView(next);
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
  if (business)
    return (
      <TemplateBuilder
        view={view}
        templates={templates}
        first={false}
        iconFor={() => Building2}
        onCancel={() => setBusiness(false)}
        onSaved={(next) => {
          setView(next);
          setBusiness(false);
        }}
        onFailed={fail}
      />
    );
  const profile =
    templates?.find((item) => item.id === view.industry)?.name ??
    "Custom stages";
  return (
    <div className={styles.stack}>
      <header className={styles.head}>
        <div>
          <h2>Lead stages</h2>
          <p>Changes save at once. Undo is in the corner.</p>
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
          className={styles.chip}
          disabled={!view.canEdit}
          onClick={() => setBusiness(true)}
        >
          <Building2 size={16} aria-hidden="true" />
          {profile}
          <ChevronRight size={16} aria-hidden="true" />
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
        <StageEditor
          view={view}
          pipeline={pipeline}
          templates={templates}
          onSaved={setView}
        />
      )}
      <div className={styles.more}>
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
      </div>
    </div>
  );
}
