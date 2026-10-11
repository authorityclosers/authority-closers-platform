"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Field, Panel, Skeleton, Table } from "./ui/kit";
import {
  inventoryImportFiles,
  type ImportSelection,
} from "./bulk-import-files";
import { previewImportFolder, type ImportPreview } from "./bulk-import-client";
import styles from "./bulk-import-preview.module.css";

/** Strike A may mount this island; no shell/page or intake activation here. */
export function BulkImportPreview({
  onPreview,
}: {
  onPreview?: (selection: ImportSelection, preview: ImportPreview) => void;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState({ done: 0, total: 0 });
  const [problem, setProblem] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(0);
  const task = useRef<AbortController | null>(null);
  useEffect(() => () => task.current?.abort(), []);

  async function select(files: File[]) {
    task.current?.abort();
    const abort = new AbortController();
    task.current = abort;
    setBusy(true);
    setProblem(null);
    setPreview(null);
    setCount({ done: 0, total: 0 });
    try {
      const selection = await inventoryImportFiles(files, {
        signal: abort.signal,
        onHashed: (done, total) => {
          if (!abort.signal.aborted) setCount({ done, total });
        },
      });
      if (abort.signal.aborted) return;
      if (selection.error !== null) {
        setProblem(selection.error);
        return;
      }
      setSkipped(selection.data.skipped);
      const result = await previewImportFolder(
        selection.data.manifest,
        abort.signal,
      );
      if (abort.signal.aborted) return;
      if (result.error !== null) {
        setProblem(result.error);
        return;
      }
      setPreview(result.data);
      onPreview?.(selection.data, result.data);
    } catch {
      if (!abort.signal.aborted)
        setProblem("Folder preview is unavailable. Try again shortly.");
    } finally {
      if (task.current === abort) {
        setBusy(false);
        task.current = null;
      }
    }
  }

  const name = (id: string | null) =>
    preview?.members.find((member) => member.personId === id)?.name ??
    "Unassigned";
  return (
    <Panel title="Import recordings">
      <div className={styles.body}>
        <Field
          label="Recording folder"
          hint="MP3, M4A, OGG, WAV or no extension · 32 MiB per recording"
        >
          <input
            type="file"
            multiple
            {...{ webkitdirectory: "", directory: "" }}
            aria-describedby="import-preview-hint"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              if (files.length) void select(files);
            }}
          />
        </Field>
        <p id="import-preview-hint" className={styles.hint}>
          Preview checks member matches. Recordings stay on your device until
          you confirm an import.
        </p>
        <div aria-live="polite" aria-busy={busy} className={styles.progress}>
          {busy ? (
            <>
              <Skeleton width={100} height={14} />
              <span>
                {count.total
                  ? `Checked ${count.done} of ${count.total} recordings`
                  : "Reading folder"}
              </span>
              <Button
                onClick={() => {
                  task.current?.abort();
                  task.current = null;
                  setBusy(false);
                }}
              >
                Cancel
              </Button>
            </>
          ) : null}
        </div>
        {preview ? (
          <>
            <Table
              label="Proposed folder members"
              cards={preview.folders.map((folder) => (
                <Card key={folder.folder}>
                  <strong title={folder.folder}>
                    {folder.folder || "Top-level recordings"}
                  </strong>
                  <span>
                    {folder.count} recordings · {name(folder.proposedPersonId)}
                  </span>
                  <Badge>
                    {folder.state === "suggested"
                      ? "Needs confirmation"
                      : folder.state === "ambiguous"
                        ? "Choose a member"
                        : "Unassigned"}
                  </Badge>
                </Card>
              ))}
            >
              <thead>
                <tr>
                  <th>Folder</th>
                  <th>Recordings</th>
                  <th>Member</th>
                </tr>
              </thead>
              <tbody>
                {preview.folders.map((folder) => (
                  <tr key={folder.folder}>
                    <td title={folder.folder}>
                      {folder.folder || "Top-level recordings"}
                    </td>
                    <td>{folder.count}</td>
                    <td>
                      {name(folder.proposedPersonId)}{" "}
                      <Badge>
                        {folder.state === "suggested"
                          ? "Needs confirmation"
                          : folder.state === "ambiguous"
                            ? "Choose a member"
                            : "Unassigned"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {skipped ? (
              <p className={styles.hint}>
                {skipped} files with other extensions were skipped.
              </p>
            ) : null}
          </>
        ) : null}
        {problem ? (
          <div className={styles.corner} role="status">
            {problem}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
