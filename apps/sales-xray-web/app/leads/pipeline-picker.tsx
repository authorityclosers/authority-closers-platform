"use client";

/**
 * The pipeline "To call now" calls from (orchestrator, 23 Oct 2026), across
 * the row's whole width (owner, Admin #3, 26 Oct 2026: "All pipelines is on
 * the left side and on the right side it's empty"): up to three pipelines are
 * one segmented control, All and each pipeline an equal part; more are a menu
 * that takes the whole row.
 */

import { Segmented } from "../ui/kit";
import { Picker } from "../ui/picker";
import styles from "./leads.module.css";

type Pipeline = Readonly<{ key: string; name: string }>;

export function PipelinePicker({
  pipelines,
  value,
  onChange,
}: {
  pipelines: readonly Pipeline[];
  /** The pipeline picked; null is all of them. */
  value: string | null;
  onChange: (next: string | null) => void;
}) {
  if (pipelines.length <= 3)
    return (
      <div className={styles.pipelineSwitch}>
        <Segmented<string>
          label="Pipeline to call"
          value={value ?? ""}
          onChange={(next) => onChange(next || null)}
          items={[
            { key: "", label: "All" },
            ...pipelines.map((item) => ({ key: item.key, label: item.name })),
          ]}
        />
      </div>
    );
  return (
    <Picker
      className={styles.pipelineChip}
      title="Pipeline to call"
      ariaLabel="Pipeline to call"
      value={value || null}
      all={{ label: "All pipelines" }}
      options={pipelines.map((item) => ({ key: item.key, label: item.name }))}
      onChange={onChange}
    />
  );
}
