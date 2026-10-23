"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { callHref } from "./acquisition-client";
import { Badge, Button, Card, Field, Panel, Table } from "./ui/kit";
import type { UploadPolicy } from "./acquisition-client";
import type { ImportPreview } from "./bulk-import-client";
import type { ImportSelection } from "./bulk-import-files";
import { BulkImportPreview } from "./bulk-import-preview";
import {
  advanceImport,
  confirmImport,
  refreshImport,
  retryImportItem,
  type ImportBatch,
  type ImportItem,
} from "./bulk-import-runner";
import styles from "./bulk-import-preview.module.css";
import actionStyles from "./bulk-recording-import.module.css";

const LABELS: Record<string, string> = {
  awaiting_upload: "Waiting to upload",
  needs_member: "Unassigned",
  expired: "Expired",
  already_imported: "Already imported",
  queued: "Queued",
  working: "Working",
  retrying: "Retrying",
  failed: "Failed",
  done: "Done",
  unavailable: "Unavailable",
};
const stateLabel = (item: ImportItem) =>
  item.memberSetupRequired
    ? "Waiting for member setup"
    : item.state === "already_imported" && item.runState
      ? `${LABELS[item.state]} · ${LABELS[item.runState]}`
      : LABELS[item.state];

/** Additive island: the page owner supplies policy and any restored batch on the server. */
export function BulkRecordingImport({
  policy,
  initialBatch = null,
}: {
  policy: UploadPolicy | null;
  initialBatch?: ImportBatch | null;
}) {
  const [selected, setSelected] = useState<ImportSelection | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [folders, setFolders] = useState<Record<string, string | null>>({});
  const [consent, setConsent] = useState(false);
  const [batch, setBatch] = useState<ImportBatch | null>(initialBatch);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const task = useRef<AbortController | null>(null);
  const confirmationKey = useRef<string | null>(null);
  const retryKeys = useRef(new Map<number, string>());

  useEffect(() => () => task.current?.abort(), []);
  useEffect(() => {
    if (!working || !batch || !selected || !consent) return;
    const abort = new AbortController();
    task.current = abort;
    const deadline = Date.now() + 60 * 60_000;
    let timer: ReturnType<typeof setTimeout>;
    let current = batch;
    async function step() {
      const latest = await refreshImport(current, abort.signal);
      if (abort.signal.aborted) return;
      if (latest.error !== null) {
        setProblem(latest.error);
        setWorking(false);
        return;
      }
      current = latest.data;
      setBatch(current);
      if (
        current.terminalState ||
        !current.items.some((item) =>
          ["awaiting_upload", "queued", "working", "retrying"].includes(
            item.state,
          ),
        )
      ) {
        setWorking(false);
        return;
      }
      if (Date.now() >= deadline) {
        setProblem(
          "Import paused after one hour. Resume to continue the remaining recordings.",
        );
        setWorking(false);
        return;
      }
      const result = await advanceImport(current, selected!, abort.signal);
      if (abort.signal.aborted) return;
      if (result.error !== null) {
        setProblem(result.error);
        setWorking(false);
        return;
      }
      timer = setTimeout(() => void step(), 3_000);
    }
    void step();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
    // The loop updates its canonical batch itself. UI progress must not restart
    // a request; consent, workspace re-selection and the run button are boundaries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [working, selected, consent, batch?.id]);

  function review(selection: ImportSelection, proposal: ImportPreview) {
    task.current?.abort();
    task.current = null;
    setWorking(false);
    setRetrying(null);
    setConsent(false);
    setProblem(null);
    if (
      batch &&
      (batch.tenantId !== proposal.tenantId ||
        batch.manifestSha !== proposal.manifestSha)
    ) {
      setProblem(
        "Choose the same folder and organisation to resume this saved import.",
      );
      return;
    }
    setSelected(selection);
    setPreview(proposal);
    setFolders(
      Object.fromEntries(
        proposal.folders.map((folder) => [
          folder.folder,
          folder.proposedPersonId,
        ]),
      ),
    );
    confirmationKey.current = null;
  }

  async function begin() {
    if (!selected || !preview || !consent || !policy || working) return;
    setProblem(null);
    if (batch) {
      setWorking(true);
      return;
    }
    const abort = new AbortController();
    task.current = abort;
    confirmationKey.current ??= `recording-import:${crypto.randomUUID()}`;
    setWorking(true);
    const result = await confirmImport({
      selection: selected,
      preview,
      folders,
      policySha: policy.policy_sha256,
      key: confirmationKey.current,
      signal: abort.signal,
    });
    if (abort.signal.aborted) return;
    if (result.error !== null) {
      setProblem(result.error);
      setWorking(false);
      return;
    }
    setBatch(result.data);
    // Start only after the exact receipt exists. A lost confirmation response
    // keeps the same key for the next explicit attempt.
    setWorking(true);
  }

  async function retry(item: ImportItem) {
    if (!batch || !consent || retrying !== null || working) return;
    setRetrying(item.index);
    setProblem(null);
    const abort = new AbortController();
    task.current = abort;
    const key =
      retryKeys.current.get(item.index) ??
      `import-retry:${crypto.randomUUID()}`;
    retryKeys.current.set(item.index, key);
    try {
      const result = await retryImportItem(batch, item, key, abort.signal);
      if (abort.signal.aborted) return;
      if (result.error !== null) setProblem(result.error);
      else {
        const read = await refreshImport(batch, abort.signal);
        if (abort.signal.aborted) return;
        if (read.error !== null) setProblem(read.error);
        else {
          setBatch(read.data);
          retryKeys.current.delete(item.index);
        }
      }
    } finally {
      if (task.current === abort) {
        task.current = null;
        setRetrying(null);
      }
    }
  }

  return (
    <div className={styles.body}>
      <BulkImportPreview onPreview={review} />
      {preview && !batch ? (
        <Panel title="Confirm folder members">
          {preview.folders.map((folder) => (
            <Field
              key={folder.folder}
              label={folder.folder || "Top-level recordings"}
            >
              <select
                aria-label={`Member for ${folder.folder || "top-level recordings"}`}
                value={folders[folder.folder] ?? ""}
                disabled={working}
                onChange={(event) => {
                  setFolders((current) => ({
                    ...current,
                    [folder.folder]: event.target.value || null,
                  }));
                  confirmationKey.current = null;
                  setConsent(false);
                }}
              >
                <option value="">Unassigned — wait for a member</option>
                {preview.members.map((member) => (
                  <option key={member.personId} value={member.personId}>
                    {member.name}
                  </option>
                ))}
              </select>
            </Field>
          ))}
        </Panel>
      ) : null}
      {preview || batch ? (
        <Panel
          title={batch ? "Recording import progress" : "Confirm the import"}
        >
          <label className={styles.consent}>
            <input
              type="checkbox"
              checked={consent}
              disabled={working}
              onChange={(event) => setConsent(event.target.checked)}
            />
            I confirm we have the right to analyse these recordings
          </label>
          <p className={styles.hint}>
            {policy?.description ?? "Upload terms are unavailable."}
          </p>
          <p className={styles.hint}>
            Confirmed members own their calls. Normal analysis and report-minute
            rules apply. Reports are prepared in English. Keep this tab open;
            pause and reselect the same folder to resume. Unassigned files wait
            for a confirmed member in a new preview.
          </p>
          <Button
            disabled={
              !consent ||
              !policy ||
              !selected ||
              working ||
              retrying !== null ||
              !!batch?.terminalState
            }
            onClick={() => void begin()}
          >
            {batch ? "Resume analysis" : "Confirm batch"}
          </Button>
          {working ? (
            <Button
              onClick={() => {
                task.current?.abort();
                setWorking(false);
              }}
            >
              Pause
            </Button>
          ) : null}
          {batch ? (
            <Table
              label="Imported recording states"
              cards={batch.items.map((item) => (
                <Card key={item.index}>
                  <span>
                    {selected?.manifest.files[item.index]?.relative_path ??
                      `Recording ${item.index + 1}`}
                  </span>
                  <Badge>{stateLabel(item)}</Badge>
                  <span>{item.stage ?? ""}</span>
                  <ImportItemActions
                    item={item}
                    disabled={!consent || working || retrying !== null}
                    onRetry={() => void retry(item)}
                  />
                </Card>
              ))}
            >
              <thead>
                <tr>
                  <th>Recording</th>
                  <th>State</th>
                  <th>Stage</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {batch.items.map((item) => (
                  <tr key={item.index}>
                    <td>
                      {selected?.manifest.files[item.index]?.relative_path ??
                        `Recording ${item.index + 1}`}
                    </td>
                    <td>{stateLabel(item)}</td>
                    <td>{item.stage ?? "—"}</td>
                    <td>
                      <ImportItemActions
                        item={item}
                        disabled={!consent || working || retrying !== null}
                        onRetry={() => void retry(item)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
          {batch ? (
            <p className={styles.hint}>
              Batch {batch.id} ·{" "}
              {
                batch.items.filter((item) =>
                  ["done", "already_imported"].includes(item.state),
                ).length
              }{" "}
              done or already imported
            </p>
          ) : null}
          {batch?.items.some((item) => item.memberSetupRequired) ? (
            <p className={styles.hint}>
              Some recordings wait for their member to add a name and phone
              number in Sales X-Ray. Ask them to finish setup, then resume. An
              import keeps its recordings for 7 days from when it started.
            </p>
          ) : null}
          {problem ? (
            <div className={styles.corner} role="status">
              {problem}
            </div>
          ) : null}
        </Panel>
      ) : null}
    </div>
  );
}

/** Saved progress links are reads, independent of consent and batch success. */
function ImportItemActions({
  item,
  disabled,
  onRetry,
}: {
  item: ImportItem;
  disabled: boolean;
  onRetry: () => void;
}) {
  return (
    <div className={actionStyles.actions}>
      {item.submissionId ? (
        <Link
          className={actionStyles.callLink}
          href={callHref(item.submissionId)}
          prefetch={false}
        >
          {item.runState === "done" ? "Open report" : "View call"}
        </Link>
      ) : null}
      {item.retryAvailable ? (
        <Button disabled={disabled} onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
