"use client";

import { useEffect, useMemo, useState, type ComponentType } from "react";
import type { AcquisitionStudio } from "../../../acquisition-studio";
import { AcquisitionShell } from "../../../acquisition-shell";
import { AcquisitionError } from "../../../acquisition-client";
import { earlyFetch } from "../../../early-reads";
import { notify } from "../../../notice-center";
import {
  preloadSavedReport,
  type SavedReportPreload,
  type ScopedSavedReport,
} from "../../../report-preload";
import { useWorkspaceAccess } from "../../../workspace-access";
import styles from "./saved-report.module.css";

type Details = typeof AcquisitionStudio;
let detailsModule: Promise<
  typeof import("../../../acquisition-studio")
> | null = null;

function loadDetails() {
  // Share code loading across a workspace change; private report data is
  // still held only in the identity-scoped component state below.
  return (detailsModule ??= import("../../../acquisition-studio").catch(
    (error: unknown) => {
      detailsModule = null;
      throw error;
    },
  ));
}

/** The verified summary loads beside the larger interactive report bundle. */
export function SavedReportPage({ callId }: { callId: string }) {
  const access = useWorkspaceAccess();
  const context =
    access?.authenticated && access.status === "ready" ? access.context : null;
  const identityKey = context
    ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
    : null;
  const key = identityKey ? `${identityKey}:${callId}` : null;
  const [loaded, setLoaded] = useState<{
    key: string;
    value: SavedReportPreload;
  } | null>(null);
  const [Details, setDetails] = useState<ComponentType<
    Parameters<Details>[0]
  > | null>(null);
  const [round, setRound] = useState(0);
  const value = loaded?.key === key ? loaded.value : null;

  useEffect(() => {
    // Give the small, authorised summary reads the connection first. Starting
    // the large details download immediately competes with them on phones.
    if (!value) return;
    let cancelled = false;
    void loadDetails().then(
      (module) => {
        if (!cancelled) setDetails(() => module.AcquisitionStudio);
      },
      () => {
        if (!cancelled)
          notify({
            id: "report-details-load",
            tone: "error",
            title: "Report details didn't load",
            message: "Your summary is safe. Try again.",
            action: {
              label: "Try again",
              run: () => setRound((value) => value + 1),
            },
          });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [round, value]);

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    void preloadSavedReport(
      callId,
      async (path, signal) => {
        const response = await earlyFetch(path, {
          signal,
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: { accept: "application/json" },
        });
        if (!response.ok) throw new AcquisitionError(response.status);
        return response.json();
      },
      controller.signal,
    ).then((value) => {
      if (!controller.signal.aborted) setLoaded({ key, value });
    });
    return () => controller.abort();
  }, [key, callId]);

  const seed = useMemo<ScopedSavedReport | undefined>(
    () =>
      value?.state === "ready" && identityKey
        ? { callId, identityKey, value }
        : undefined,
    [callId, identityKey, value],
  );
  // Processing, permission errors and retries keep the studio's existing flow.
  if (Details && value)
    return <Details requestedCallId={callId} initialSavedReport={seed} />;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      active="analyse"
      mobileFit
      pageName="Report"
      loading={!context}
    >
      <div className={styles.opening} data-report-opening="">
        <section
          className={styles.summary}
          aria-label="Call summary"
          aria-busy={!seed}
        >
          <h2>Call summary</h2>
          {seed ? (
            <p data-report-summary-preview="">
              {seed.value.result.report.summary}
            </p>
          ) : (
            <div
              className={styles.lines}
              aria-label="Loading call summary"
              role="status"
            >
              <i />
              <i />
              <i />
            </div>
          )}
        </section>
        <div
          className={styles.details}
          role="status"
          aria-label="Loading report details"
        >
          <i />
          <i />
          <i />
        </div>
      </div>
    </AcquisitionShell>
  );
}
