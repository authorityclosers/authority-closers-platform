"use client";

/**
 * Undo import and Import history (competitor teardown 22, 1 Nov 2026): owners
 * and admins, for 48 hours, from the import's result and from the list of
 * recent imports. One confirm says what goes (the leads nobody has worked) and
 * what stays; the answer names each lead kept and why ("Has a note").
 */

import { RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  ago,
  commandId,
  LeadsError,
  readImports,
  undoImport,
  type ImportUndone,
  type ImportView,
} from "./leads-client";
import deleteStyles from "./delete-leads.module.css";
import styles from "./import-undo.module.css";

const plural = (count: number, one: string, many: string) =>
  `${count} ${count === 1 ? one : many}`;

/** The answer in words: "8 leads removed. 2 kept: a seller already worked them." */
export function undoneWords(result: ImportUndone): string {
  const removed = result.removed
    ? `${plural(result.removed, "lead", "leads")} removed.`
    : "Nothing removed.";
  if (!result.kept.length) return removed;
  return `${removed} ${result.kept.length} kept: a seller already worked ${
    result.kept.length === 1 ? "it" : "them"
  }.`;
}

/** "Undo import" and its confirm; the answer stays in the sheet with the kept leads. */
export function UndoImportButton({
  importId,
  onUndone,
}: {
  importId: string;
  onUndone: (result: ImportUndone) => void;
}) {
  const [round, setRound] = useState(0);
  return (
    <>
      <Button variant="ghost" onClick={() => setRound((value) => value + 1)}>
        <RotateCcw size={15} aria-hidden="true" />
        Undo import
      </Button>
      {round ? (
        <UndoImportSheet
          key={round}
          importId={importId}
          onClose={() => setRound(0)}
          onUndone={onUndone}
        />
      ) : null}
    </>
  );
}

function UndoImportSheet({
  importId,
  onClose,
  onUndone,
}: {
  importId: string;
  onClose: () => void;
  onUndone: (result: ImportUndone) => void;
}) {
  // One confirm, one command: Undo again after a problem changes nothing twice.
  const [command] = useState(commandId);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportUndone | null>(null);
  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = await undoImport(importId, command);
      setResult(next);
      onUndone(next);
    } catch (reason) {
      notify({
        id: "import-undo",
        tone: "error",
        title: "The import wasn't undone",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Sales X-Ray isn't answering. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={result ? "Import undone" : "Undo this import?"}
      description={result ? undoneWords(result) : undefined}
      lead={
        <span className={deleteStyles.mark} aria-hidden="true">
          <RotateCcw size={18} />
        </span>
      }
      closeButton={false}
      wide="center"
      className={deleteStyles.sheet}
      footer={
        result ? (
          <div className={deleteStyles.actions}>
            <Button variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        ) : (
          <div className={deleteStyles.actions}>
            <Button variant="ghost" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <button
              type="button"
              className={deleteStyles.danger}
              disabled={busy}
              onClick={() => void confirm()}
            >
              <RotateCcw size={15} aria-hidden="true" />
              {busy ? "Undoing…" : "Undo import"}
            </button>
          </div>
        )
      }
    >
      {result ? (
        result.kept.length ? (
          <ul className={styles.kept} aria-label="Kept">
            {result.kept.map((lead) => (
              <li key={lead.lead_id}>
                <span>{lead.name}</span>
                <small>{lead.why}</small>
              </li>
            ))}
          </ul>
        ) : null
      ) : (
        <>
          <p className={deleteStyles.text}>
            The leads from this file that nobody has worked yet leave Leads for
            good.
          </p>
          <p className={deleteStyles.keep}>
            A lead a seller already called, noted or moved stays, and so does a
            number that was a lead before.
          </p>
        </>
      )}
    </Sheet>
  );
}

/** Recent imports (the last 48 hours), each with its Undo while it can. */
export function ImportHistory({
  onChanged,
  now = () => new Date(),
}: {
  onChanged: () => void;
  now?: () => Date;
}) {
  const [imports, setImports] = useState<ImportView[] | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    readImports(controller.signal).then(setImports, () => setImports([]));
    return () => controller.abort();
  }, [version]);
  if (!imports?.length) return null;
  return (
    <section className={styles.history} aria-label="Recent imports">
      <h3>Recent imports</h3>
      <ul>
        {imports.map((item) => (
          <li key={item.import_id}>
            <span className={styles.what}>
              <strong>{item.file_name}</strong>
              <small>
                {[
                  plural(item.leads, "lead", "leads"),
                  item.by_name,
                  ago(item.at, now()),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </span>
            {item.undone ? (
              <span className={styles.undone}>Undone</span>
            ) : item.undo_until && item.leads > 0 ? (
              <UndoImportButton
                importId={item.import_id}
                onUndone={() => {
                  setVersion((value) => value + 1);
                  onChanged();
                }}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
