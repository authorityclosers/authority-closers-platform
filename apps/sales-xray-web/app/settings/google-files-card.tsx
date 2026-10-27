"use client";

/**
 * Settings → Connected apps → Google (Sheets and Drive) (Lead OS, slice 1,
 * 27 Oct 2026): connect once, then import a Sheet someone picks (Lead sources
 * and Import) and keep a copy of every new lead in a Sheet in the
 * organisation's Drive. Sales X-Ray sees only the files picked and the ones it
 * makes. Hidden where the server doesn't offer it yet, or for members.
 */

import { AlertTriangle, ExternalLink, FolderOpen, PlugZap } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";

import { notify } from "../notice-center";
import { useAppConnect } from "../leads/app-connect";
import { SwitchRow } from "../leads/app-card";
import {
  disconnectGoogleFiles,
  GOOGLE_FILES_CONNECT,
  GoogleFilesError,
  keepSheetCopy,
  readGoogleFiles,
  stopSheetCopy,
  type GoogleFiles,
} from "../leads/google-files-client";
import { BrandTile } from "../ui/brand-tile";
import { Badge, Button } from "../ui/kit";
import { ago } from "./connected-apps-client";
import styles from "./connected-apps.module.css";

type Loaded = { state: "loading" } | { state: "hidden" } | GoogleFiles;

/** What the card says under its name. */
export function googleFilesWords(files: GoogleFiles): string {
  if (!files.configured)
    return "Import from Google Sheets and keep a copy of your leads there. Coming soon.";
  if (!files.connected)
    return "Import leads from a Sheet you pick, and keep a copy of new leads in a Sheet of your own. Sales X-Ray sees only the files you pick.";
  return [
    files.email,
    files.connected_by ? `connected by ${files.connected_by}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function GoogleFilesCard() {
  const titleId = useId();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const read = useCallback((signal?: AbortSignal) => {
    readGoogleFiles(signal).then(setLoaded, (reason: unknown) => {
      if (signal?.aborted) return;
      // Not offered here (an older server) or not for this person: no card.
      setLoaded({ state: "hidden" });
      if (
        reason instanceof GoogleFilesError &&
        ![401, 403, 404].includes(reason.status)
      )
        notify({
          id: "google-files",
          tone: "error",
          title: "Google Sheets and Drive didn’t load",
          message: reason.message,
        });
    });
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    read(controller.signal);
    return () => controller.abort();
  }, [read]);

  // Inside the phone app the Connect opens in the browser; this page finishes it.
  const connectInApp = useAppConnect(
    "google",
    (outcome) => {
      if (outcome.result === "connected") {
        notify({
          id: "google-files",
          tone: "success",
          title: "Google Sheets and Drive is connected",
          timeout: 6000,
        });
        read();
      } else
        notify({
          id: "google-files",
          tone: outcome.result === "cancelled" ? "info" : "error",
          title: "Google wasn’t connected",
          message: outcome.message ?? "Try again in a moment.",
        });
    },
    GOOGLE_FILES_CONNECT,
  );

  const change = async (run: () => Promise<GoogleFiles>, failed: string) => {
    setBusy(true);
    try {
      setLoaded(await run());
    } catch (reason) {
      notify({
        id: "google-files",
        tone: "error",
        title: failed,
        message:
          reason instanceof GoogleFilesError
            ? reason.message
            : "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
      setLeaving(false);
    }
  };

  if ("state" in loaded && loaded.state === "hidden") return null;
  if ("state" in loaded)
    return (
      <article
        className={styles.card}
        aria-busy="true"
        aria-label="Google Sheets and Drive"
      />
    );

  const files = loaded;
  const copy = files.copy;
  const problem = copy?.on ? copy.problem : null;
  return (
    <article
      className={styles.card}
      data-app="google_files"
      data-state={
        !files.configured
          ? "not_set_up"
          : problem
            ? "problem"
            : files.connected
              ? "ready"
              : "not_connected"
      }
      aria-labelledby={titleId}
    >
      <div className={styles.cardHead}>
        <BrandTile brands={["googlesheets", "googledrive"]} size={44} />
        <div className={styles.cardTitle}>
          <h3 id={titleId}>Google Sheets and Drive</h3>
          <Badge
            tone={
              !files.configured || !files.connected
                ? "neutral"
                : problem
                  ? "warn"
                  : "good"
            }
          >
            {!files.configured
              ? "Coming soon"
              : !files.connected
                ? "Not connected"
                : problem
                  ? "Needs attention"
                  : "Connected"}
          </Badge>
        </div>
      </div>
      <p className={styles.words}>{googleFilesWords(files)}</p>
      {files.connected ? (
        <SwitchRow
          label="Keep a copy in Google Sheets"
          hint={
            copy?.on
              ? [
                  `${copy.sent} lead${copy.sent === 1 ? "" : "s"} added`,
                  copy.last_sent_at ? `last ${ago(copy.last_sent_at)}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "Every new lead is added to a Sheet in your Drive within a minute."
          }
          checked={Boolean(copy?.on)}
          disabled={busy}
          onChange={(on) =>
            void change(
              on ? keepSheetCopy : stopSheetCopy,
              on ? "The copy didn’t start" : "The copy didn’t stop",
            )
          }
        />
      ) : null}
      {problem ? (
        <p className={styles.reviewLine} role="status">
          <AlertTriangle size={13} aria-hidden="true" />
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        {!files.configured ? null : !files.connected ? (
          <a
            href={GOOGLE_FILES_CONNECT}
            className={styles.linkButton}
            data-variant="tinted"
            onClick={connectInApp}
          >
            <PlugZap size={15} aria-hidden="true" />
            Connect
          </a>
        ) : (
          <>
            {copy?.on && copy.url ? (
              <a
                href={copy.url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.linkButton}
                data-variant="secondary"
              >
                <ExternalLink size={15} aria-hidden="true" />
                Open the Sheet
              </a>
            ) : null}
            {files.folder_url ? (
              <a
                href={files.folder_url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.linkButton}
                data-variant="secondary"
              >
                <FolderOpen size={15} aria-hidden="true" />
                Drive folder
              </a>
            ) : null}
            {leaving ? (
              <>
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    void change(
                      disconnectGoogleFiles,
                      "Google wasn’t disconnected",
                    )
                  }
                >
                  Disconnect Google
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setLeaving(false)}
                >
                  Keep it
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setLeaving(true)}
              >
                Disconnect
              </Button>
            )}
          </>
        )}
      </div>
      {leaving ? (
        <p className={styles.words}>
          New leads stop going to the Sheet; the Sheet and your files stay in
          your Drive.
        </p>
      ) : null}
    </article>
  );
}
