"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { notify } from "../../notice-center";
import { Skeleton } from "../../ui/kit";
import { Picker } from "../../ui/picker";
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
import editorStyles from "./stage-editor.module.css";
import styles from "./setup.module.css";

/** Lead stages (owner + Dipak, 31 Oct 2026): the title, one line, the editor. Every
 *  way here (Leads setup, More → Lead stages, Settings) shows this one screen; `bare`
 *  leaves the title to a page that has its own (lead-stages-screen.tsx). */
export function OrganisationStages({ bare = false }: { bare?: boolean }) {
  const [view, setView] = useState<JourneyView | null>(null);
  const [pipes, setPipes] = useState<PipelinesView | null>(null);
  const [templates, setTemplates] = useState<TemplateView[] | null>(null);
  const [pipeline, setPipeline] = useState(() =>
    typeof window === "undefined"
      ? "main"
      : (new URLSearchParams(window.location.search).get("pipeline") ?? "main"),
  );
  const [ads, setAds] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
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
          notify({
            id: "org-stage",
            tone: "error",
            title: "Stages didn't load",
            message: reason instanceof Error ? reason.message : "Try again.",
          });
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
            <Skeleton height={240} />
            <Skeleton height={432} />
          </div>
        )}
      </div>
    );
  if (ads)
    return (
      <div className={styles.stack}>
        <button
          type="button"
          className={editorStyles.back}
          onClick={() => setAds(false)}
        >
          <ChevronLeft size={18} aria-hidden="true" />
          Lead stages
        </button>
        <AdPlatforms version={view.version} />
      </div>
    );
  return (
    <div className={styles.stack}>
      {bare ? null : (
        <header className={styles.head}>
          <div>
            <h2>Lead stages</h2>
            <p>What your sellers see</p>
          </div>
        </header>
      )}
      {pipes && pipes.pipelines.length > 1 ? (
        <Picker
          title="Stage list"
          ariaLabel="Stage list"
          value={pipeline}
          options={pipes.pipelines.map((item) => ({
            key: item.key,
            label: item.name,
          }))}
          onChange={(key) => {
            if (key !== null) choosePipeline(key);
          }}
        />
      ) : null}
      <StageEditor
        key={pipeline}
        view={view}
        pipeline={pipeline}
        templates={templates}
        onSaved={setView}
      />
      {pipeline === "main" && view.canEdit ? (
        <button
          type="button"
          className={editorStyles.linkRow}
          onClick={() => setAds(true)}
        >
          Ad platforms
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
