"use client";

/**
 * Edit the fixed costs a month (owner, 23 Oct 2026: fixed costs editable in Admin). One
 * save is one new revision, checked against the revision read and audited with old and new
 * (PUT /v1/admin/economics/settings). The measured line (AI on test calls) is read from the
 * metrics store and is not edited here.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { Field, kitStyles } from "../ui/kit";
import type { FixedItem } from "./economics-data";
import styles from "./economics.module.css";

type Row = {
  key: string;
  label: string;
  rupees: string;
  kind: string;
  source: string;
};

const toRow = (item: FixedItem): Row => ({
  key: item.key,
  label: item.label,
  rupees: String(item.rupees),
  kind: item.kind,
  source: item.source,
});

const slug = (label: string, taken: Set<string>) => {
  const base =
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[^a-z]+/, "")
      .slice(0, 32) || "cost";
  let key = base.length > 1 ? base : `${base}_cost`;
  let n = 2;
  while (taken.has(key)) key = `${base}_${n++}`;
  return key;
};

export function FixedCostsEditor({
  revision,
  config,
  items,
}: {
  revision: number | null;
  config: Record<string, unknown>;
  items: FixedItem[];
}) {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>(
    items.filter((item) => item.source !== "measured").map(toRow),
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  const change = (index: number, field: keyof Row, value: string) =>
    setRows((current) =>
      current.map((row, at) =>
        at === index ? { ...row, [field]: value } : row,
      ),
    );

  async function save() {
    const bad = rows.find(
      (row) =>
        !row.label.trim() ||
        row.rupees.trim() === "" ||
        !Number.isFinite(Number(row.rupees)) ||
        Number(row.rupees) < 0,
    );
    if (bad) {
      setMessage({
        ok: false,
        text: "Each cost needs a name and an amount of 0 or more.",
      });
      return;
    }
    setBusy(true);
    setMessage(null);
    const result = await send(
      "PUT",
      "/v1/admin/economics/settings",
      {
        expected_revision: revision,
        config: {
          ...config,
          fixed: rows.map((row) => ({
            key: row.key,
            label: row.label.trim(),
            rupees: Number(row.rupees),
            kind: row.kind,
            source: row.source,
          })),
        },
        reason: reason.trim() || "Fixed costs edited in Admin",
      },
      null,
    );
    setBusy(false);
    if (!result.ok) {
      setMessage({ ok: false, text: result.message });
      return;
    }
    setMessage({
      ok: true,
      text: "Saved. Margins and break-even use these now.",
    });
    router.refresh();
  }

  return (
    <form
      className={styles.editor}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {rows.map((row, index) => (
        <fieldset key={row.key} className={styles.editRow}>
          <legend className={styles.srOnly}>{row.label || "New cost"}</legend>
          <Field label="Cost">
            <input
              value={row.label}
              maxLength={120}
              onChange={(event) => change(index, "label", event.target.value)}
            />
          </Field>
          <Field label="₹ a month">
            <input
              inputMode="decimal"
              value={row.rupees}
              onChange={(event) => change(index, "rupees", event.target.value)}
            />
          </Field>
          <Field label="Kind">
            <select
              value={row.kind}
              onChange={(event) => change(index, "kind", event.target.value)}
            >
              <option value="running">Running</option>
              <option value="building">Building (agents)</option>
            </select>
          </Field>
          <Field label="From">
            <select
              value={row.source}
              onChange={(event) => change(index, "source", event.target.value)}
            >
              <option value="estimate">Estimate</option>
              <option value="invoice">Invoice</option>
            </select>
          </Field>
          <button
            type="button"
            className={kitStyles.button}
            data-variant="ghost"
            aria-label={`Remove ${row.label || "this cost"}`}
            onClick={() =>
              setRows((current) => current.filter((_, at) => at !== index))
            }
          >
            Remove
          </button>
        </fieldset>
      ))}
      <div className={styles.editFoot}>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="secondary"
          onClick={() =>
            setRows((current) => [
              ...current,
              {
                key: slug("cost", new Set(current.map((row) => row.key))),
                label: "",
                rupees: "0",
                kind: "running",
                source: "invoice",
              },
            ])
          }
        >
          Add a cost
        </button>
        <Field label="Why (kept in the audit log)" wide>
          <input
            value={reason}
            maxLength={200}
            placeholder="e.g. Hostinger invoice for October"
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={busy}
        >
          {busy ? "Saving…" : "Save fixed costs"}
        </button>
        {message ? (
          <small
            className={message.ok ? styles.saved : kitStyles.fieldError}
            role={message.ok ? "status" : "alert"}
          >
            {message.text}
          </small>
        ) : null}
      </div>
    </form>
  );
}
