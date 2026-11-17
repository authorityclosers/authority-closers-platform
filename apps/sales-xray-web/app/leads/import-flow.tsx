"use client";

/**
 * Importing a lead file, as a full-page workspace (owner's picks, 17 Nov 2026: lead
 * import I1-A "amazing … the icons", I1-B's "Which sheet has your leads?"; study
 * docs/design/research/lead-import-and-management-20261116, 01 §5 S1).
 *
 * File → Match columns → Check → Assign, then the receipt in place. On a computer it is
 * a wide workspace over Leads (no 420 px dialog); on a phone it is full screen with a
 * 4-part progress bar and the button fixed at the bottom. The file step offers the drop
 * area, Google Sheets, a Facebook lead form file, pasted rows, a sample file and the
 * recent imports with Undo; an Excel file with several sheets asks which has the leads
 * and shows its first rows before matching.
 */

import {
  ArrowLeft,
  Check,
  ChevronRight,
  ClipboardPaste,
  FileSpreadsheet,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { askFeedback } from "../feedback/ask";
import { settingsPath } from "../settings/settings-sections";
import { useBackClose } from "../ui/back-close";
import { BrandTile } from "../ui/brand-tile";
import { Button, Field } from "../ui/kit";
import { Picker } from "../ui/picker";
import { useNarrow } from "./import-narrow";
import {
  countsFor,
  firstChoices,
  freshRows,
  sellersOf,
  serverAssign,
  sharesFor,
  sharing,
  type UploadChoices,
} from "./bulk-upload";
import {
  GoogleFilesError,
  previewGoogleSheet,
  readGoogleFiles,
  type GoogleFiles,
} from "./google-files-client";
import { PICKER_FAILED, pickGoogleSheet } from "./google-picker";
import { ImportCheck } from "./import-check";
import {
  FileCheckLines,
  fileOwnersLine,
  ownedByFile,
  useFileCheck,
} from "./import-file-check";
import styles from "./import-flow.module.css";
import {
  columnRows,
  COLUMN_LABELS,
  isSerialColumn,
  KEEP,
  MatchCounts,
  MatchedCard,
  MatchPairs,
  MatchQuestion,
  MatchSheet,
  questionsOf,
  SKIP,
  useImportStages,
  type MatchProps,
  type MatchState,
  type Question,
} from "./import-match";
import matchStyles from "./import-match.module.css";
import {
  FileOwnersNote,
  phoneSummary,
  SummaryCard,
  summaryLines,
} from "./import-assign";
import assignStyles from "./import-assign.module.css";
import { ImportReceipt } from "./import-receipt";
import { outcomeCounts, rowViews, RowsCheck } from "./import-rows";
import { ImportHistory } from "./import-undo";
import {
  commandId,
  commitImport,
  LeadsError,
  previewImport,
  readTeam,
  SAMPLE_CSV,
  type Duplicates,
  type ImportPreview,
  type ImportResult,
  type RepView,
} from "./leads-client";
import leadStyles from "./leads.module.css";
import { inPhoneApp, openConnect } from "./native-phone";
import { OldLeadsCheck, useOldLeads, waitReason } from "./old-leads";
import { PASTED_FILE, pastedFile, readPasted } from "./paste-import";
import {
  overLimitLines,
  sharesLine,
  UploadChoicesFields,
} from "./upload-choices";
import { several, usePipelines } from "./use-pipelines";

/** The import's steps (owner's pick I1-A, 17 Nov 2026: File · Match columns · Check
 *  · Assign). */
type ImportStep = "file" | "columns" | "check" | "who";
const IMPORT_STEPS: { key: ImportStep; label: string }[] = [
  { key: "file", label: "File" },
  { key: "columns", label: "Match columns" },
  { key: "check", label: "Check" },
  { key: "who", label: "Assign" },
];

const plural = (count: number, one: string, many: string) =>
  `${count.toLocaleString("en-IN")} ${count === 1 ? one : many}`;

/** "48 KB" / "1.2 MB": a picked file's size, as the file card says it. */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "Leads · 12 rows · 11 columns" / "Summary · no leads": a sheet in the picker. */
export function sheetLine(sheet: { rows: number; columns: number }): string {
  if (!sheet.rows) return "no leads";
  return `${plural(sheet.rows, "row", "rows")} · ${plural(sheet.columns, "column", "columns")}`;
}

/** A file over the limit is said, never cut silently (study 01 §5 S1). */
export const OVER_LIMIT =
  "This file has more than 2,000 rows. Only the first 2,000 come in: split it into files of 2,000 to bring in the rest.";

function PipelinePick({
  open,
  value,
  onChange,
}: {
  open: boolean;
  value: string;
  onChange: (next: string) => void;
}) {
  const pipes = usePipelines(open);
  if (!several(pipes)) return null;
  return (
    <Field label="Pipeline">
      <Picker
        title="Pipeline"
        mode="inline"
        value={value || null}
        all={{ label: "Where file imports go" }}
        options={pipes.pipelines.map((item) => ({
          key: item.key,
          label: item.name,
        }))}
        onChange={(key) => onChange(key ?? "")}
      />
    </Field>
  );
}

/** One of the "Other ways" rows: an icon tile, a title, a line, a chevron. */
function WayRow({
  icon,
  title,
  text,
  onClick,
  disabled,
  pressed,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
}) {
  return (
    <button
      type="button"
      className={styles.way}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={pressed}
    >
      <span className={styles.wayIcon}>{icon}</span>
      <span className={styles.wayText}>
        <strong>{title}</strong>
        <small>{text}</small>
      </span>
      <ChevronRight size={18} aria-hidden="true" className={styles.chev} />
    </button>
  );
}

/** The file read: which sheet has the leads (several sheets only), its first rows. */
function FileRead({
  preview,
  size,
  busy,
  onSheet,
  onAnother,
}: {
  preview: ImportPreview;
  size: number | null;
  busy: boolean;
  onSheet: (name: string) => void;
  onAnother: () => void;
}) {
  const sheets = preview.sheets ?? [];
  const pasted = preview.file_name === PASTED_FILE;
  const headers = preview.headers;
  const first = preview.rows.slice(0, 3);
  return (
    <div className={styles.read} data-import-read="">
      <div className={styles.fileCard}>
        <BrandTile brands={[pasted ? "" : "excel"]} icon={FileSpreadsheet} />
        <span className={styles.fileName}>
          <strong>{pasted ? "Pasted rows" : preview.file_name}</strong>
          <small>
            {[
              sheets.length > 1
                ? plural(sheets.length, "sheet", "sheets")
                : plural(preview.total_rows, "row", "rows"),
              size !== null ? fileSize(size) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </small>
        </span>
        <button type="button" className={styles.textLink} onClick={onAnother}>
          Choose another file
        </button>
      </div>
      {sheets.length > 1 ? (
        <section aria-labelledby="import-sheets">
          <h3 id="import-sheets" className={styles.h3}>
            Which sheet has your leads?
          </h3>
          <div
            className={styles.sheets}
            role="radiogroup"
            aria-label="Which sheet has your leads?"
          >
            {sheets.map((sheet) => {
              const on = sheet.name === preview.sheet;
              return (
                <button
                  key={sheet.name}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className={styles.sheet}
                  data-sheet={sheet.name}
                  disabled={busy}
                  onClick={() => {
                    if (!on) onSheet(sheet.name);
                  }}
                >
                  <span className={styles.radio} aria-hidden="true">
                    {on ? <Check size={14} strokeWidth={3} /> : null}
                  </span>
                  <strong>{sheet.name}</strong>
                  <span className={styles.muted}> · {sheetLine(sheet)}</span>
                </button>
              );
            })}
          </div>
        </section>
      ) : null}
      <section aria-labelledby="import-first-rows">
        <h3 id="import-first-rows" className={styles.h3}>
          First rows
        </h3>
        <div className={styles.tableWrap}>
          <table className={styles.firstRows}>
            <thead>
              <tr>
                {headers.map((header, index) => (
                  <th key={header} data-extra={index > 1 ? "" : undefined}>
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {first.map((row, index) => (
                <tr key={index}>
                  {headers.map((header, column) => (
                    <td key={header} data-extra={column > 1 ? "" : undefined}>
                      {row[header] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {headers.length > 2 ? (
          <p className={styles.moreColumns}>
            + {plural(headers.length - 2, "more column", "more columns")}
          </p>
        ) : null}
      </section>
      <p className={styles.found} role="status" data-import-found="">
        <Check size={16} strokeWidth={2.5} aria-hidden="true" />
        Found {plural(preview.total_rows, "row", "rows")}
        {` · ${plural(headers.length, "column", "columns")}`}. The first row is
        read as the column names.
      </p>
      {preview.truncated ? (
        <p className={styles.warn} role="status" data-import-over="">
          {OVER_LIMIT}
        </p>
      ) : null}
    </div>
  );
}

export function ImportFlow({
  open,
  canManage,
  onClose,
  onDone,
  onLanded,
  pasted = null,
  google = false,
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onDone: () => void;
  /** Done: show the side the new leads went to (ph1-17: it opened Inbound). */
  onLanded?: (side: "inbound" | "cold") => void;
  /** Rows pasted into the list's quick add: read as soon as it opens. */
  pasted?: string | null;
  /** Opened to import a Google Sheet (Lead sources → Import from Google
   *  Sheet): Google's Picker opens as soon as Google is known connected. */
  google?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useBackClose(open, onClose);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close?.();
  }, [open]);

  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  // Bulk upload (stages-views-sources.md section 5): Cold Leads by default, who receives
  // the new leads and how many each, and the stage they start in.
  const [choices, setChoices] = useState<UploadChoices>(() =>
    firstChoices(canManage),
  );
  const [team, setTeam] = useState<RepView[] | null>(null);
  // Everyone on the team: a file's owner names may be any of them (I2).
  const [everyone, setEveryone] = useState<RepView[] | null>(null);
  useEffect(() => {
    if (!open || !canManage) return;
    let live = true;
    readTeam().then(
      (next) => {
        // New leads are shared between sellers only (owner, 2 Nov 2026).
        if (live) {
          setTeam(sellersOf(next.reps));
          setEveryone(next.reps);
        }
      },
      () => {
        if (live) {
          setTeam([]);
          setEveryone([]);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [open, canManage]);
  const [pipeline, setPipeline] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const command = useRef(commandId());
  // Rows pasted from a sheet, a CSV or a chat (owner P0, 23 Oct 2026).
  const [text, setText] = useState("");
  const [pasting, setPasting] = useState(false);
  const [dropped, setDropped] = useState(0);
  // The file picked, kept to read another of its sheets (I1-B).
  const picked = useRef<File | null>(null);
  const [size, setSize] = useState<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // File, Match columns, Check, Assign: a file whose columns matched opens on
  // Check, Import there with the defaults (the owner's one click, 25 Oct 2026);
  // otherwise Match columns first. An Excel file with several sheets first asks
  // which has the leads (I1-B). Numbers already leads are skipped unless an
  // owner or admin picks Fill blanks or Replace.
  const [step, setStep] = useState<ImportStep>("file");
  const [duplicates, setDuplicates] = useState<Duplicates>("skip");
  // Matching (I2): columns not imported, columns looked at, the stage each unknown
  // stage word is, the teammate each unknown owner name is ("" = the lead rules).
  const [skip, setSkip] = useState<string[]>([]);
  const [answered, setAnswered] = useState<string[]>([]);
  const [stagePicks, setStagePicks] = useState<Record<string, string>>({});
  const [ownerPicks, setOwnerPicks] = useState<Record<string, string>>({});
  // I2-B, the sheet with labels: "Advanced" on a computer.
  const [advanced, setAdvanced] = useState(false);
  // I2-C on a phone: the matched pairs on demand, the questions passed and the one
  // on screen (kept there once answered, until Next question).
  const [seeAll, setSeeAll] = useState(false);
  const [passed, setPassed] = useState<string[]>([]);
  const [held, setHeld] = useState<Question | null>(null);
  const narrow = useNarrow();
  // Old leads (owner, 2 Nov 2026): the file says each lead's day, stage, campaign and
  // salesperson, so there is no Assign step; Check says what each stage word becomes.
  const history = choices.side === "history";
  // Every file goes through Match columns (owner's pick: I2-A is the default progression).
  const go = (next: ImportPreview) => {
    const start = history
      ? { ...next.mapping, ...next.history_mapping }
      : next.mapping;
    setMapping(start);
    // Row numbers ("Sr No") start as not imported, as do the server's own picks
    // (remembered, or a Facebook lead form's ids).
    const used = new Set(Object.values(start));
    const remembered = new Set(next.remembered ?? []);
    setSkip([
      ...new Set([
        ...(next.skip ?? []),
        ...next.headers.filter(
          (header) =>
            isSerialColumn(header) &&
            !used.has(header) &&
            !remembered.has(header),
        ),
      ]),
    ]);
    setAnswered([]);
    setStagePicks({});
    setOwnerPicks({});
    setPassed([]);
    setHeld(null);
    setStep("columns");
  };
  const landed = (next: ImportPreview) => {
    setPreview(next);
    // Several sheets: stay on File to ask which has the leads.
    if ((next.sheets?.length ?? 0) > 1) {
      setMapping({});
      setStep("file");
      return;
    }
    go(next);
  };

  // A Sheet picked in Google's Picker (Lead OS, 27 Oct 2026): owners and
  // admins, once Google Sheets and Drive is connected.
  const [googleFiles, setGoogleFiles] = useState<GoogleFiles | null>(null);
  useEffect(() => {
    if (!open || !canManage) return;
    const controller = new AbortController();
    readGoogleFiles(controller.signal).then(setGoogleFiles, () =>
      setGoogleFiles(null),
    );
    return () => controller.abort();
  }, [open, canManage]);
  const googleReady = Boolean(googleFiles?.connected && googleFiles.picker);
  // The Picker found Google no longer connected: say where to connect it.
  const [googleLost, setGoogleLost] = useState(false);
  const fromGoogle = async () => {
    // The Picker needs a real browser page: the phone app opens one.
    if (inPhoneApp()) {
      void openConnect(
        new URL("/leads?import=google", window.location.origin).href,
      );
      return;
    }
    setBusy(true);
    setError(null);
    let sheet: string | null = null;
    try {
      sheet = await pickGoogleSheet();
      if (!sheet) return;
      picked.current = null;
      setSize(null);
      landed(await previewGoogleSheet(sheet));
    } catch (reason) {
      // 409 from the Picker's setup: Google isn't connected (any more).
      if (
        !sheet &&
        reason instanceof GoogleFilesError &&
        reason.status === 409
      ) {
        setGoogleLost(true);
        setGoogleFiles(
          (current) => current && { ...current, connected: false },
        );
        return;
      }
      setError(
        reason instanceof GoogleFilesError || reason instanceof LeadsError
          ? reason.message
          : PICKER_FAILED,
      );
    } finally {
      setBusy(false);
    }
  };
  const fromGoogleLatest = useRef(fromGoogle);
  useEffect(() => {
    fromGoogleLatest.current = fromGoogle;
  });
  // Arrived for a Google Sheet: the Picker opens once Google is known ready;
  // without Google connected, the page says where to connect it.
  const googleMissing =
    (google || googleLost) &&
    canManage &&
    googleFiles !== null &&
    !(googleFiles.connected && googleFiles.picker);
  const googleAsked = useRef(false);
  useEffect(() => {
    if (!open || !google || !googleReady || googleAsked.current) return;
    if (inPhoneApp()) return;
    googleAsked.current = true;
    void fromGoogleLatest.current();
  }, [open, google, googleReady]);

  const read = async (file: File, sheet?: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await previewImport(file, sheet);
      picked.current = file;
      setSize(file.name === PASTED_FILE ? null : file.size);
      landed(next);
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "That file couldn't be read.",
      );
    } finally {
      setBusy(false);
    }
  };
  const pick = async (file: File | undefined) => {
    if (!file) return;
    await read(file);
  };

  const readText = (value: string) => {
    const rows = readPasted(value);
    if (!rows) {
      setError(
        "There are no rows in that. Copy the rows from your sheet, with their headings if it has them.",
      );
      return;
    }
    setDropped(rows.dropped);
    void pick(pastedFile(rows));
  };
  const reading = useRef(readText);
  useEffect(() => {
    reading.current = readText;
  });
  const handed = useRef(false);
  useEffect(() => {
    if (!open || !pasted || handed.current) return;
    handed.current = true;
    setText(pasted);
    setPasting(true);
    reading.current(pasted);
  }, [open, pasted]);

  const sent = useMemo(() => {
    if (!preview || !skip.length) return preview;
    const out = new Set(skip);
    return {
      ...preview,
      headers: preview.headers.filter((header) => !out.has(header)),
      rows: preview.rows.map((row) =>
        Object.fromEntries(
          Object.entries(row).filter(([header]) => !out.has(header)),
        ),
      ),
    };
  }, [preview, skip]);
  const ownersSent = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(ownerPicks).filter(([, person]) => person),
      ),
    [ownerPicks],
  );
  // A number fixed on Check (I3): the row changes and the check runs again.
  const [fixes, setFixes] = useState(0);
  const fixPhone = (row: number, phone: string) => {
    const header = mapping.phone;
    if (!header) return;
    setPreview((current) =>
      current
        ? {
            ...current,
            rows: current.rows.map((line, index) =>
              index === row ? { ...line, [header]: phone } : line,
            ),
          }
        : current,
    );
    setFixes((count) => count + 1);
  };
  // New leads: their stages, owners and columns, before Import (owner's import
  // study, 16 Nov 2026). Rows that name a teammate keep that teammate whatever
  // is picked under Assign; only the rest are shared.
  const fileCheck = useFileCheck({
    on:
      open &&
      ((!history && (step === "check" || step === "who")) ||
        step === "columns") &&
      !result,
    preview: sent,
    mapping,
    side: choices.side === "cold" ? "cold" : "live",
    step: choices.step,
    pipeline,
    stages: stagePicks,
    owners: ownersSent,
    version: fixes,
  });
  // New leads: the check's count of new rows when it has one, else the preview's.
  const checkedRows = fileCheck.check?.rows ?? [];
  const fresh = !preview
    ? 0
    : checkedRows.length && !history
      ? checkedRows.filter((item) => item.outcome === "new").length
      : freshRows(preview);
  const stagesList = useImportStages(
    open && (step === "columns" || step === "who"),
    pipeline,
  );
  const match: MatchState | null = preview
    ? {
        preview,
        mapping,
        skip,
        answered,
        check: fileCheck.check,
        stagePicks,
        ownerPicks,
        history,
        canManage,
      }
    : null;
  // A column's new place: a field (taken from the column that had it), kept on the
  // lead, or not imported.
  const placeColumn = (header: string, choice: string) => {
    setMapping((current) => {
      const next: Record<string, string> = {};
      for (const [field, column] of Object.entries(current))
        if (column !== header && field !== choice) next[field] = column;
      if (choice !== KEEP && choice !== SKIP) next[choice] = header;
      return next;
    });
    setSkip((current) =>
      choice === SKIP
        ? [...current.filter((item) => item !== header), header]
        : current.filter((item) => item !== header),
    );
  };
  const questions = match && step === "columns" ? questionsOf(match) : [];
  const waiting = questions.filter((item) => !passed.includes(item.id));
  const current =
    held && !passed.includes(held.id) ? held : (waiting[0] ?? null);
  const hold = () => {
    if (current) setHeld(current);
  };
  const matchProps: MatchProps = {
    match: match!,
    stages: stagesList,
    side: choices.side,
    people: everyone,
    onColumn: placeColumn,
    onStage: (word, stage) =>
      setStagePicks((picks) => ({ ...picks, [word]: stage })),
    onOwner: (name, person) =>
      setOwnerPicks((picks) => ({ ...picks, [name]: person })),
  };
  const nextQuestion = () => {
    if (current) setPassed((ids) => [...ids, current.id]);
    setHeld(null);
  };
  const owned = Math.min(fresh, ownedByFile(fileCheck));
  const toShare = fresh - owned;
  // The owners the file names are still being checked: the split waits for them.
  const ownersPending =
    !history &&
    canManage &&
    Boolean(mapping.owner) &&
    fileCheck.check === null &&
    fileCheck.error === null;
  const whoLine = owned
    ? toShare
      ? `${owned} keep their owner from your file; the other ${toShare}: ${sharesLine(choices, team, toShare)}`
      : "All keep their owner from your file."
    : sharesLine(choices, team, fresh);
  // Old leads go to nobody: who gets them never holds Import back.
  const assigning = !history && sharing(choices.assign);
  const overGiven =
    assigning &&
    team !== null &&
    Object.values(countsFor(choices, team, toShare)).reduce(
      (sum, count) => sum + count,
      0,
    ) > toShare;
  // An even split needs the team: Import waits for it.
  const teamPending = canManage && assigning && team === null;
  // "One seller" waits for the seller to be picked.
  const nobodyPicked = !history && choices.assign === "one" && !choices.one;
  const noColumn = !mapping.name && !mapping.phone;
  const limits =
    canManage && !history ? overLimitLines(choices, team, toShare) : [];
  const old = useOldLeads({
    on: open && history && step === "check" && !result,
    preview: sent,
    mapping,
    pipeline,
  });
  // Import waits, with one plain reason, until every stage word has a stage.
  const oldWait = history ? waitReason(old) : null;

  const run = async () => {
    if (!preview) return;
    if (noColumn) {
      setError("Choose the column with the name or the phone number.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Remembered for the next import: the columns kept or left out on purpose.
      const kept = answered.filter(
        (header) =>
          !skip.includes(header) && !Object.values(mapping).includes(header),
      );
      const memory = {
        ...(Object.keys(ownersSent).length ? { owners: ownersSent } : {}),
        ...(skip.length ? { skipped: skip } : {}),
        ...(kept.length ? { kept } : {}),
      };
      setResult(
        await commitImport(
          sent ?? preview,
          mapping,
          history ? "none" : serverAssign(choices.assign),
          command.current,
          pipeline || null,
          history
            ? {
                side: "history",
                stages: { ...stagePicks, ...old.chosen },
                ...memory,
                ...(duplicates !== "skip" ? { duplicates } : {}),
              }
            : {
                side: choices.side,
                ...(Object.keys(stagePicks).length
                  ? { stages: stagePicks }
                  : {}),
                ...memory,
                ...(sharing(choices.assign) && team
                  ? { shares: sharesFor(choices, team, toShare) }
                  : {}),
                ...(choices.step ? { step: choices.step } : {}),
                ...(duplicates !== "skip" ? { duplicates } : {}),
              },
        ),
      );
      onDone();
      // Reviews engine: how the first import went, asked once.
      askFeedback("first_import", { subject: "first-import" });
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The import didn't finish. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const another = () => {
    setError(null);
    setPreview(null);
    setMapping({});
    setDropped(0);
    setSize(null);
    picked.current = null;
    setStep("file");
  };
  const back = () => {
    setError(null);
    if (step === "who") setStep("check");
    else if (step === "check") setStep("columns");
    // Back from Match columns: the sheets again, or choose another file.
    else if (step === "columns" && (preview?.sheets?.length ?? 0) > 1)
      setStep("file");
    else another();
  };
  // The header's back arrow: a step back, or out of the import from its start.
  const headBack = () => {
    if (result || (step === "file" && !preview)) onClose();
    else back();
  };

  const again = () => {
    setResult(null);
    command.current = commandId();
    setDuplicates("skip");
    another();
  };
  const finish = () => {
    // Old leads land in no list: the page stays where it was.
    if (result?.side && result.side !== "history" && onLanded)
      onLanded(result.side === "cold" ? "cold" : "inbound");
    onClose();
  };

  // The file in a line: whose export, its name and how many rows.
  const fileLine = preview ? (
    <p className={leadStyles.hint}>
      {preview.detected ? `${preview.detected} export. ` : ""}
      {preview.file_name === PASTED_FILE ? "Pasted" : preview.file_name}
      {preview.sheet && (preview.sheets?.length ?? 0) > 1
        ? ` (${preview.sheet})`
        : ""}
      : {preview.total_rows} rows
      {preview.truncated || dropped ? " (only the first 2,000)" : ""}.
    </p>
  ) : null;
  const limitBox = limits.length ? (
    // Said before the import, never only after (ph1-17).
    <div
      className={leadStyles.importWarnings}
      role="status"
      data-import-limit=""
    >
      {limits.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  ) : null;

  // I4-A: what Import does, line by line, beside who gets the leads.
  const summaryRows =
    preview && checkedRows.length
      ? rowViews(sent ?? preview, mapping, fileCheck.check)
      : [];
  const fileOwners = fileOwnersLine(fileCheck.check);
  const startStage = stagesList?.find((stage) => stage.key === choices.step);
  const stageLine = mapping.stage
    ? `Stages from your file${startStage ? `; the rest start in ${startStage.label}` : ""}`
    : startStage
      ? `Starting in ${startStage.label}`
      : `Starting in ${stagesList?.[0]?.label ?? "the first stage"}`;
  const notImported = summaryRows.length
    ? (() => {
        const counts = outcomeCounts(summaryRows);
        return counts.known + counts.repeat + counts.cant;
      })()
    : 0;
  const sellersGiven = new Set([
    ...(fileCheck.check?.owners ?? [])
      .map((owner) => owner.person_id)
      .filter(Boolean),
    ...(team && sharing(choices.assign) && toShare
      ? Object.entries(countsFor(choices, team, toShare))
          .filter(([, count]) => count > 0)
          .map(([person]) => person)
      : choices.assign === "one" && choices.one
        ? [choices.one]
        : []),
  ]).size;

  const visibleSteps = IMPORT_STEPS.filter(
    (item) => !history || item.key !== "who",
  );
  const at = Math.max(
    0,
    visibleSteps.findIndex((item) => item.key === step),
  );
  const fileRead = step === "file" && preview !== null && !result;

  const importButton = (
    <Button
      variant="primary"
      onClick={run}
      disabled={
        busy ||
        // The check of what is on screen now must be back (PR 634 P2).
        (!history && fileCheck.check === null) ||
        ownersPending ||
        overGiven ||
        teamPending ||
        nobodyPicked ||
        noColumn ||
        (step === "check" && oldWait !== null)
      }
    >
      {busy
        ? "Importing…"
        : fresh
          ? `Import ${fresh} ${history ? "old " : ""}lead${fresh === 1 ? "" : "s"}`
          : "Import"}
    </Button>
  );
  const actions = result ? (
    <>
      <Button onClick={again}>Import another file</Button>
      <Button variant="primary" onClick={finish}>
        {result.side === "history" || !result.created
          ? "Done"
          : `See the ${result.created} ${result.created === 1 ? "lead" : "leads"}`}
      </Button>
    </>
  ) : step === "file" && !preview ? null : fileRead ? (
    <>
      <Button onClick={another} disabled={busy}>
        Cancel
      </Button>
      <Button
        variant="primary"
        onClick={() => preview && go(preview)}
        disabled={busy}
      >
        Match columns
      </Button>
    </>
  ) : (
    <>
      <Button onClick={back} disabled={busy}>
        Back
      </Button>
      {step === "columns" ? (
        narrow && current ? (
          <Button variant="primary" onClick={nextQuestion}>
            Next question
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={() => setStep("check")}
            disabled={noColumn}
          >
            {narrow ? "Continue" : "Continue to check leads"}
          </Button>
        )
      ) : step === "check" && !history ? (
        // Import only on Assign, after who gets them (study 01 §3: never skipped).
        <Button
          variant="primary"
          onClick={() => setStep("who")}
          disabled={fileCheck.check === null || noColumn}
        >
          {narrow ? "Continue" : "Continue to assign"}
        </Button>
      ) : (
        importButton
      )}
    </>
  );

  return (
    <dialog
      ref={ref}
      className={styles.flow}
      aria-labelledby={titleId}
      data-import-flow=""
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open ? (
        <div className={styles.frame}>
          <header className={styles.head}>
            <button
              type="button"
              className={styles.icon}
              aria-label="Back"
              title="Back"
              onClick={headBack}
            >
              <ArrowLeft size={20} aria-hidden="true" />
            </button>
            <h2 id={titleId} className={styles.title}>
              Import leads
            </h2>
            {result ? null : (
              <span className={styles.count} aria-hidden="true">
                {at + 1} of {visibleSteps.length}
              </span>
            )}
            <button
              type="button"
              className={`${styles.icon} ${styles.close}`}
              aria-label="Close"
              title="Close"
              onClick={onClose}
            >
              <X size={20} aria-hidden="true" />
            </button>
          </header>
          {result ? null : (
            <>
              <ol className={styles.steps} aria-label="Import steps">
                {visibleSteps.map((item, index) => (
                  <li
                    key={item.key}
                    aria-current={item.key === step ? "step" : undefined}
                    data-done={index < at ? "" : undefined}
                  >
                    <span aria-hidden="true">{index + 1}</span>
                    {item.label}
                  </li>
                ))}
              </ol>
              <div className={styles.bar} aria-hidden="true">
                {visibleSteps.map((item, index) => (
                  <i key={item.key} data-on={index <= at ? "" : undefined} />
                ))}
              </div>
            </>
          )}
          <div className={styles.body}>
            <div className={styles.content}>
              {result && preview ? (
                <ImportReceipt
                  result={result}
                  preview={sent ?? preview}
                  duplicates={duplicates}
                  stageFromFile={Boolean(mapping.stage)}
                  onUndone={onDone}
                />
              ) : null}
              {result?.side === "history" ? (
                <p className={leadStyles.hint}>
                  The old leads are in Leads, under Filter → Date → Old leads,
                  and in Analytics under All time.
                  {result.undated
                    ? ` ${result.undated} had no enquiry date we could read: ${result.undated === 1 ? "it shows" : "they show"} today.`
                    : ""}
                </p>
              ) : null}
              {result?.unmatched_stages?.length ? (
                <p className={leadStyles.hint}>
                  No stage called {result.unmatched_stages.join(", ")}: those
                  leads start in{" "}
                  {fileCheck.check?.unmatched_stage ?? "the first stage"}, and
                  keep the file&apos;s word on the lead.
                </p>
              ) : null}
              {/* People the import took past their limit (Lead OS, 25 Oct 2026):
                  said as written, as a warning; an import never hides it. */}
              {result?.warnings?.length ? (
                <div
                  className={leadStyles.importWarnings}
                  role="status"
                  data-import-warnings=""
                >
                  {result.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                  {canManage ? (
                    <Link href={settingsPath("lead-rules")}>Change limits</Link>
                  ) : null}
                </div>
              ) : null}
              {result?.unmatched_owners?.length ? (
                <p className={leadStyles.hint}>
                  Nobody on your team called{" "}
                  {result.unmatched_owners.join(", ")}:
                  {result.side === "history"
                    ? " those old leads have no salesperson."
                    : " those leads went by the lead rules."}
                </p>
              ) : null}
              {result ? null : fileRead && preview ? (
                <FileRead
                  preview={preview}
                  size={size}
                  busy={busy}
                  onAnother={another}
                  onSheet={(name) => {
                    if (picked.current) void read(picked.current, name);
                  }}
                />
              ) : step === "file" || !preview ? (
                <div className={styles.start}>
                  <div className={styles.intro}>
                    <h3 className={styles.hero}>Bring in your leads</h3>
                    <p className={styles.muted}>
                      Excel, CSV or a Google Sheet, up to 2,000 leads. We match
                      the columns for you, and every column is kept on the lead.
                    </p>
                  </div>
                  <div className={styles.ways}>
                    <label
                      className={styles.drop}
                      data-busy={busy ? "" : undefined}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => {
                        event.preventDefault();
                        void pick(event.dataTransfer.files?.[0]);
                      }}
                    >
                      <BrandTile icon={FileSpreadsheet} size={56} />
                      {busy ? (
                        <strong className={styles.dropTitle}>
                          Reading your file…
                        </strong>
                      ) : (
                        <>
                          <strong
                            className={`${styles.dropTitle} ${styles.wide}`}
                          >
                            Drop your file here
                          </strong>
                          <span className={`${styles.muted} ${styles.wide}`}>
                            or
                          </span>
                          <span className={`${styles.pill} ${styles.wide}`}>
                            Choose a file
                          </span>
                          <span className={`${styles.muted} ${styles.wide}`}>
                            Excel (.xlsx) or CSV
                          </span>
                          <strong
                            className={`${styles.dropTitle} ${styles.narrow}`}
                          >
                            Choose an Excel or CSV file
                          </strong>
                          <span className={`${styles.muted} ${styles.narrow}`}>
                            From Downloads, WhatsApp or Drive
                          </span>
                        </>
                      )}
                      <input
                        ref={fileInput}
                        type="file"
                        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        disabled={busy}
                        onChange={(event) => {
                          void pick(event.target.files?.[0]);
                          event.target.value = "";
                        }}
                      />
                    </label>
                    <div className={styles.other}>
                      <h3 className={`${styles.h3} ${styles.wide}`}>
                        Other ways
                      </h3>
                      {canManage ? (
                        googleReady ? (
                          <WayRow
                            icon={
                              <BrandTile brands={["googlesheets"]} size={36} />
                            }
                            title="Google Sheet"
                            text={
                              busy
                                ? "Opening Google…"
                                : "Pick a sheet from your Drive"
                            }
                            disabled={busy}
                            onClick={() => void fromGoogle()}
                          />
                        ) : (
                          <Link
                            className={styles.way}
                            href={settingsPath("apps")}
                          >
                            <span className={styles.wayIcon}>
                              <BrandTile brands={["googlesheets"]} size={36} />
                            </span>
                            <span className={styles.wayText}>
                              <strong>Google Sheet</strong>
                              <small>Connect Google Sheets first</small>
                            </span>
                            <ChevronRight
                              size={18}
                              aria-hidden="true"
                              className={styles.chev}
                            />
                          </Link>
                        )
                      ) : null}
                      <WayRow
                        icon={<BrandTile brands={["facebook"]} size={36} />}
                        title="Facebook lead form file"
                        text="Upload the CSV you downloaded"
                        disabled={busy}
                        onClick={() => fileInput.current?.click()}
                      />
                      <WayRow
                        icon={<BrandTile icon={ClipboardPaste} size={36} />}
                        title="Paste rows"
                        text="From a sheet, a chat or ChatGPT"
                        disabled={busy}
                        pressed={pasting}
                        onClick={() => setPasting((on) => !on)}
                      />
                      {pasting ? (
                        <div className={styles.paste}>
                          <textarea
                            aria-label="Paste rows"
                            rows={4}
                            value={text}
                            disabled={busy}
                            placeholder="Paste rows from a sheet, a CSV or ChatGPT"
                            onChange={(event) => {
                              setText(event.target.value);
                              setError(null);
                            }}
                            onPaste={(event) => {
                              const value = event.clipboardData.getData("text");
                              if (!value.trim()) return;
                              event.preventDefault();
                              setText(value);
                              readText(value);
                            }}
                          />
                          <Button
                            onClick={() => readText(text)}
                            disabled={busy || !text.trim()}
                          >
                            Read rows
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {googleMissing ? (
                    <p className={leadStyles.hint} role="status">
                      Connect Google Sheets and Drive first:{" "}
                      <Link href={settingsPath("apps")}>
                        Settings → Connected apps
                      </Link>
                      .
                    </p>
                  ) : null}
                  <a
                    className={styles.sample}
                    href={`data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`}
                    download="sales-xray-leads-sample.csv"
                  >
                    Download a sample file
                  </a>
                  {/* Cold Leads unless picked otherwise (section 5). */}
                  <section className={styles.where} aria-label="Where they go">
                    <UploadChoicesFields
                      part="side"
                      canManage={canManage}
                      team={team}
                      fresh={fresh}
                      pipeline={pipeline}
                      value={choices}
                      onChange={setChoices}
                    />
                    {canManage ? (
                      <PipelinePick
                        open={open}
                        value={pipeline}
                        onChange={setPipeline}
                      />
                    ) : null}
                  </section>
                  {canManage ? (
                    <div className={styles.recent}>
                      <ImportHistory onChanged={onDone} />
                    </div>
                  ) : null}
                </div>
              ) : step === "columns" && match ? (
                <div className={styles.match} data-import-match="">
                  {fileLine}
                  <div className={matchStyles.top}>
                    <div>
                      <h3 className={matchStyles.title}>Match your columns</h3>
                      <p className={matchStyles.muted}>
                        We matched what we recognised.
                        {narrow ? "" : " Check the marked rows."}
                      </p>
                    </div>
                    {narrow ? null : <MatchCounts rows={columnRows(match)} />}
                  </div>
                  {narrow ? (
                    <>
                      <MatchedCard
                        rows={columnRows(match)}
                        open={seeAll}
                        onToggle={() => setSeeAll((on) => !on)}
                      />
                      {seeAll ? <MatchPairs {...matchProps} /> : null}
                      {current ? (
                        <>
                          <p className={matchStyles.qCount}>
                            Question {passed.length + 1} of{" "}
                            {passed.length +
                              waiting.length +
                              (waiting.some((item) => item.id === current.id)
                                ? 0
                                : 1)}
                          </p>
                          <MatchQuestion
                            key={current.id}
                            question={current}
                            props={{
                              ...matchProps,
                              onColumn: (header, choice) => {
                                hold();
                                placeColumn(header, choice);
                              },
                              onStage: (word, stage) => {
                                hold();
                                matchProps.onStage(word, stage);
                              },
                              onOwner: (name, person) => {
                                hold();
                                matchProps.onOwner(name, person);
                              },
                            }}
                            onAnswered={(header) =>
                              setAnswered((list) =>
                                list.includes(header)
                                  ? list
                                  : [...list, header],
                              )
                            }
                          />
                          <button
                            type="button"
                            className={`${matchStyles.link} ${matchStyles.skipFor}`}
                            onClick={nextQuestion}
                          >
                            Skip for now
                          </button>
                        </>
                      ) : (
                        <p className={matchStyles.foot}>
                          No questions: every column is accounted for.
                        </p>
                      )}
                    </>
                  ) : (
                    <>
                      {advanced ? (
                        <MatchSheet {...matchProps} />
                      ) : (
                        <MatchPairs {...matchProps} />
                      )}
                      <button
                        type="button"
                        className={`${matchStyles.link} ${matchStyles.advanced}`}
                        onClick={() => setAdvanced((on) => !on)}
                      >
                        {advanced
                          ? "Back to the list of columns"
                          : "Advanced: match on your sheet"}
                      </button>
                    </>
                  )}
                  <p
                    className={matchStyles.foot}
                    data-warn={noColumn ? "" : undefined}
                    role={noColumn ? "alert" : undefined}
                  >
                    {noColumn
                      ? "Choose the column with the name or the phone number."
                      : history
                        ? "Every column is accounted for. Salespeople are matched to your team; one that doesn't match leaves the lead with nobody."
                        : "Every column is accounted for. A column kept on the lead shows under its own name."}
                  </p>
                </div>
              ) : step === "check" ? (
                <>
                  {fileLine}
                  <p className={leadStyles.hint}>
                    Columns matched:{" "}
                    {Object.keys(mapping)
                      .filter((field) => mapping[field])
                      .map((field) => COLUMN_LABELS[field] ?? field)
                      .join(", ")}
                    .{" "}
                    <button
                      type="button"
                      className={leadStyles.linkButton}
                      onClick={() => setStep("columns")}
                    >
                      Change columns
                    </button>
                  </p>
                  {history || !checkedRows.length ? null : (
                    <RowsCheck
                      preview={sent ?? preview}
                      mapping={mapping}
                      check={fileCheck.check}
                      narrow={narrow}
                      canManage={canManage}
                      duplicates={duplicates}
                      onDuplicates={setDuplicates}
                      onFix={fixPhone}
                    />
                  )}
                  {/* Old leads: the first rows as they will be, before Import (phone
                      personas ph1-48 and competitor teardown 5). */}
                  {history ? (
                    <ul
                      className={leadStyles.hint}
                      aria-label="The first rows, as leads"
                    >
                      {preview.rows.slice(0, 3).map((row, index) => (
                        <li key={index}>
                          {[
                            mapping.name,
                            mapping.phone,
                            history ? mapping.received : null,
                            history ? mapping.stage : null,
                            mapping.campaign ?? mapping.source,
                          ]
                            .map((column) =>
                              column ? row[column]?.trim() : "",
                            )
                            .filter(Boolean)
                            .join(" · ") || "No name or phone in this row"}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {/* Old leads, or a check without rows (still reading, or an
                      older server): the counts as before. */}
                  {history || !checkedRows.length ? (
                    <ImportCheck
                      preview={preview}
                      fresh={fresh}
                      canManage={canManage}
                      duplicates={duplicates}
                      onDuplicates={setDuplicates}
                    />
                  ) : fileCheck.error ? (
                    <FileCheckLines
                      state={fileCheck}
                      stageColumn={mapping.stage}
                    />
                  ) : null}
                  {history ? (
                    <>
                      {/* Old leads: each stage word and what it becomes (no Assign step). */}
                      <OldLeadsCheck state={old} />
                      {oldWait && old.check ? (
                        <p
                          className={leadStyles.hint}
                          role="status"
                          data-import-wait=""
                        >
                          {oldWait}
                        </p>
                      ) : null}
                    </>
                  ) : (
                    /* Who gets them, in a line; Change opens the last step. */
                    <p className={leadStyles.hint} data-import-who="">
                      {canManage
                        ? `About ${fresh} new ${fresh === 1 ? "lead" : "leads"}: ${whoLine}`
                        : "They go on your desk."}{" "}
                      <button
                        type="button"
                        className={leadStyles.linkButton}
                        onClick={() => setStep("who")}
                      >
                        Change
                      </button>
                    </p>
                  )}
                  {limitBox}
                </>
              ) : (
                <div className={assignStyles.layout} data-import-assign="">
                  <div className={assignStyles.head}>
                    <h3 className={assignStyles.title}>
                      Assign owners and other details
                    </h3>
                    <p className={assignStyles.muted}>
                      {fresh} new {fresh === 1 ? "lead" : "leads"} will be
                      created.
                    </p>
                  </div>
                  <div className={assignStyles.choices}>
                    <FileOwnersNote owners={fileOwners} rest={toShare} />
                    <UploadChoicesFields
                      part="who"
                      canManage={canManage}
                      team={team}
                      fresh={toShare}
                      pipeline={pipeline}
                      value={choices}
                      onChange={setChoices}
                    />
                    {canManage ? (
                      <p className={leadStyles.hint}>
                        About {fresh} new {fresh === 1 ? "lead" : "leads"}:{" "}
                        {whoLine}
                      </p>
                    ) : null}
                    {limitBox}
                  </div>
                  <SummaryCard
                    lines={summaryLines({
                      rows: summaryRows,
                      fresh,
                      side: choices.side === "cold" ? "cold" : "live",
                      owners: fileOwners,
                      whoLine: canManage ? whoLine : "On your desk.",
                      stageLine,
                      keptWords:
                        duplicates === "fill"
                          ? "empty details filled"
                          : duplicates === "replace"
                            ? "details replaced"
                            : "left as it is",
                    })}
                    action={null}
                    footnote={
                      canManage
                        ? "You can undo this import for 48 hours in Recent imports."
                        : null
                    }
                  />
                  <p className={assignStyles.phoneLine} data-phone-summary="">
                    {phoneSummary(fresh, sellersGiven, notImported)}
                  </p>
                </div>
              )}
              {error ? (
                <p className={leadStyles.error} role="alert">
                  {error}
                </p>
              ) : null}
            </div>
          </div>
          {actions ? <footer className={styles.foot}>{actions}</footer> : null}
        </div>
      ) : null}
    </dialog>
  );
}
