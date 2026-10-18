"use client";

/**
 * Admin → Call data: which model each pipeline uses, on/off and the daily
 * rupee cap (owner rule: every provider is swappable in Admin; keys stay in
 * Infisical). Saves are append-only revisions; a stale page is refused.
 */

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Field } from "../ui/kit";
import {
  toApi,
  type CallDataSettings,
  type PipelineConfig,
} from "./call-data-model";
import styles from "./call-data-settings.module.css";

const PIPELINES: { key: "fast" | "deep"; label: string; sub: string }[] = [
  {
    key: "fast",
    label: "Fast pipeline",
    sub: "Every new call, seconds after its transcript: fills the lead and asks the seller.",
  },
  {
    key: "deep",
    label: "Deep pipeline",
    sub: "Reads the whole call and classifies everything. Arrives in v0.64.",
  },
];

export function CallDataSettingsForm({
  settings,
}: {
  settings: CallDataSettings;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState(settings.config);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const change = (key: "fast" | "deep", patch: Partial<PipelineConfig>) =>
    setDraft((current) => ({
      ...current,
      [key]: { ...current[key], ...patch },
    }));

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/v1/admin/call-data/settings", {
        method: "PUT",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          expected_revision: settings.revision,
          config: toApi(draft),
        }),
      });
      if (!response.ok) {
        setMessage(
          response.status === 409
            ? "Someone changed these settings. Refresh and try again."
            : response.status === 403
              ? "Use your verified AC Admin account to change these."
              : "Not saved. Check the values and try again.",
        );
        return;
      }
      setMessage("Saved. The runner uses it from its next pass.");
      router.refresh();
    } catch {
      setMessage("Not saved. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.form}>
      {PIPELINES.map((pipeline) => {
        const config = draft[pipeline.key];
        return (
          <fieldset key={pipeline.key} className={styles.pipeline}>
            <legend>
              {pipeline.label}{" "}
              <Badge tone={config.enabled ? "good" : "neutral"}>
                {config.enabled ? "On" : "Off"}
              </Badge>
            </legend>
            <p className={styles.sub}>{pipeline.sub}</p>
            <label className={styles.toggle}>
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={(event) =>
                  change(pipeline.key, { enabled: event.target.checked })
                }
              />
              Run this pipeline
            </label>
            <Field label="Model">
              <select
                className={styles.input}
                value={config.model}
                onChange={(event) =>
                  change(pipeline.key, { model: event.target.value })
                }
              >
                {settings.models.map((model) => (
                  <option key={model.model} value={model.model}>
                    {model.label} (${model.inputUsd} in / ${model.outputUsd} out
                    per M tokens)
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Daily cap (₹, list-price estimate)">
              <input
                className={styles.input}
                type="number"
                min={0}
                max={5000}
                value={config.dailyCapInr}
                onChange={(event) =>
                  change(pipeline.key, {
                    dailyCapInr: Number(event.target.value) || 0,
                  })
                }
              />
            </Field>
            <Field label="Longest call it reads (minutes)">
              <input
                className={styles.input}
                type="number"
                min={1}
                max={120}
                value={config.maxCallMinutes}
                onChange={(event) =>
                  change(pipeline.key, {
                    maxCallMinutes: Number(event.target.value) || 1,
                  })
                }
              />
            </Field>
          </fieldset>
        );
      })}
      <div className={styles.actions}>
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          <Save size={14} aria-hidden="true" />
          Save settings
        </Button>
        {message ? (
          <span className={styles.message} role="status">
            {message}
          </span>
        ) : null}
      </div>
    </div>
  );
}
