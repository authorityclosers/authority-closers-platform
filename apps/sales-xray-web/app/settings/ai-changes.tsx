"use client";

/**
 * Settings → AI apps, part two (owner order, 25 Oct 2026; docs/product/ai-writes.md):
 * the notes and tasks AI apps and API keys added to leads in the last 30 days, each
 * with Undo for 7 days, and for owners and admins the workspace's switch that pauses
 * every change from apps. Shown only in an organisation, where leads live.
 */
import { useCallback, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import { SwitchRow } from "../leads/app-card";
import { notify } from "../notice-center";
import { Badge, Button, Empty, List, Panel, Row, SkeletonRow } from "../ui/kit";
import {
  changeWords,
  dayWords,
  readAiWrites,
  readAppChanges,
  saveAiWrites,
  undoAppChange,
  type AiWritesSwitch,
  type AppChange,
} from "./ai-apps-client";
import styles from "./ai-apps.module.css";

export function AppChangesPanel() {
  const [changes, setChanges] = useState<AppChange[] | null | "none">(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback((signal?: AbortSignal) => {
    readAppChanges(signal).then(
      (next) => setChanges(next ?? "none"),
      () => {
        if (signal?.aborted) return;
        notify({
          id: "ai-changes",
          tone: "error",
          title: "Changes from AI apps did not load",
          message: "Open this page again in a moment.",
        });
      },
    );
  }, []);
  useEffect(() => {
    const control = new AbortController();
    load(control.signal);
    return () => control.abort();
  }, [load]);

  if (changes === "none") return null;
  const undo = (change: AppChange) => {
    setBusy(change.id);
    undoAppChange(change.id).then(
      () => {
        setBusy(null);
        notify({
          id: "ai-changes",
          tone: "success",
          title: "Undone",
          message:
            change.action === "task"
              ? "The task is cancelled. The lead’s history keeps it."
              : "The note no longer shows. The lead’s history keeps it.",
        });
        load();
      },
      (reason: unknown) => {
        setBusy(null);
        notify({
          id: "ai-changes",
          tone: "error",
          title: "Not undone",
          message:
            reason instanceof Error && reason.message
              ? reason.message
              : "Try again in a moment.",
        });
      },
    );
  };
  return (
    <Panel
      title="Changes from AI apps"
      sub={
        Array.isArray(changes) && changes.length
          ? `${changes.length}`
          : undefined
      }
    >
      {changes === null ? (
        <div className={styles.outline} aria-busy="true">
          <SkeletonRow />
          <SkeletonRow />
        </div>
      ) : changes.length === 0 ? (
        <Empty
          icon={Sparkles}
          title="No changes from AI apps"
          text="Notes and tasks an AI app adds to your leads show here for 30 days, with Undo for 7."
        />
      ) : (
        <List label="Changes from AI apps">
          {changes.map((change) => (
            <Row
              key={change.id}
              title={`${changeWords(change.action)} · ${change.leadName ?? "A deleted lead"}`}
              meta={[`via ${change.via}`, dayWords(change.at)]}
              end={
                change.status === "undone" ? (
                  <Badge>Undone</Badge>
                ) : change.canUndo ? (
                  <Button
                    variant="secondary"
                    disabled={busy === change.id}
                    onClick={() => undo(change)}
                  >
                    {busy === change.id ? "Undoing…" : "Undo"}
                  </Button>
                ) : null
              }
            />
          ))}
        </List>
      )}
    </Panel>
  );
}

/** Owners and admins: pause every change from apps, or one kind. */
export function AiWritesPanel() {
  const [current, setCurrent] = useState<AiWritesSwitch | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const control = new AbortController();
    readAiWrites(control.signal).then(setCurrent, () => undefined);
    return () => control.abort();
  }, []);
  if (!current || !current.canChange) return null;
  const save = (next: AiWritesSwitch) => {
    setBusy(true);
    saveAiWrites(next).then(
      (saved) => {
        setCurrent(saved);
        setBusy(false);
      },
      () => {
        setBusy(false);
        notify({
          id: "ai-writes",
          tone: "error",
          title: "Not saved",
          message: "Someone may have changed this. Open the page again.",
        });
      },
    );
  };
  return (
    <Panel title="AI apps in this workspace">
      <SwitchRow
        label="Let AI apps and API keys add to leads"
        hint="Off pauses every change from apps here at once. Reading still works."
        checked={!current.paused}
        disabled={busy}
        onChange={(on) => save({ ...current, paused: !on })}
      >
        <SwitchRow
          label="Notes"
          checked={current.note}
          disabled={busy}
          onChange={(on) => save({ ...current, note: on })}
        />
        <SwitchRow
          label="Tasks and reminders"
          checked={current.task}
          disabled={busy}
          onChange={(on) => save({ ...current, task: on })}
        />
      </SwitchRow>
    </Panel>
  );
}
