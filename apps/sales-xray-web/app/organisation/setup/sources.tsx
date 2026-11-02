"use client";
import { Link2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { notify } from "../../notice-center";
import { useAppConnect } from "../../leads/app-connect";
import { readGoogleFiles } from "../../leads/google-files-client";
import {
  SourcesView,
  type MetaForm,
  type MetaPage,
} from "../../leads/sources-view";
import { BrandTile } from "../../ui/brand-tile";
import { Skeleton } from "../../ui/kit";
import { MetaAccounts, testOnly, topLine } from "./meta-accounts";
import { metaRequest, refreshForms, type MetaCatalogue } from "./meta-client";
import { MicrophoneAccess } from "./microphone";
import styles from "./setup.module.css";

const outcomes: Record<string, string> = {
  connected: "Facebook connected. Turn on the Pages that bring leads.",
  nopages:
    "No Pages shared. Sign in with the account that manages the Page and allow access.",
  cancelled: "Facebook sign-in cancelled. Your connections are unchanged.",
  failed: "Facebook sign-in did not finish. Connect again.",
};

/**
 * Leads setup → Sources. Facebook & Instagram first, by the account that
 * shared each Page (owner, 2 Nov 2026: which account connected which Pages,
 * which bring leads, and remove a wrong account or old Pages; it replaced one
 * long list of every form with a save bar). Other sources, help and the
 * microphone check sit in folded rows at the end.
 */
export function OrganisationSources() {
  const params = useSearchParams();
  const router = useRouter();
  const [showOther, setShowOther] = useState(false);
  // Import from Google Sheet (Drive's picker) only where Google is set up, as
  // Connected apps says (phone personas ph1-23, 1 Nov 2026); a Sheet's link
  // (Google Sheet) works either way.
  const [googlePicker, setGooglePicker] = useState(false);
  useEffect(() => {
    if (!showOther) return;
    const controller = new AbortController();
    readGoogleFiles(controller.signal).then(
      (files) => setGooglePicker(files.configured && files.picker),
      () => setGooglePicker(false),
    );
    return () => controller.abort();
  }, [showOther]);
  const [catalogue, setCatalogue] = useState<MetaCatalogue | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const control = new AbortController();
    request.current = control;
    try {
      const next = await metaRequest<MetaCatalogue>(
        "/status",
        undefined,
        AbortSignal.any([control.signal, AbortSignal.timeout(12000)]),
      );
      if (control.signal.aborted) return;
      if (!Array.isArray(next.pages)) throw new Error("No catalogue");
      setCatalogue(next);
      setFailed(false);
      // A Page that brings leads shows its forms as Meta has them now: the
      // list kept with it can be days old for a Page that takes some forms.
      await refreshForms(
        next.pages.filter((page) => page.active && !page.removed),
        (id, listed) => {
          if (!listed) return;
          setCatalogue((current) =>
            current
              ? {
                  ...current,
                  pages: current.pages.map((page) =>
                    page.pageId === id
                      ? { ...page, formsOnPage: listed as MetaForm[] }
                      : page,
                  ),
                }
              : current,
          );
        },
        control.signal,
      );
    } catch {
      if (control.signal.aborted) return;
      setFailed(true);
      notify({
        id: "meta-catalogue",
        tone: "error",
        title: "Facebook Pages didn't load",
        message: "Your saved connections are kept.",
        action: {
          label: "Try again",
          run: () => setAttempt((value) => value + 1),
        },
      });
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => {
      clearTimeout(timer);
      request.current?.abort();
    };
  }, [load, attempt]);
  useEffect(() => {
    const result = params.get("meta");
    if (result && outcomes[result])
      notify({
        id: "meta-return",
        tone: result === "connected" ? "success" : "info",
        title: outcomes[result],
      });
  }, [params]);
  const complete = ({
    result,
    message,
  }: {
    result: string;
    message?: string;
  }) => {
    notify({
      id: "meta-connect",
      tone: result === "connected" ? "success" : "info",
      title: message ?? outcomes[result] ?? outcomes.failed,
    });
    if (result === "connected") void load();
  };
  // The exact start preserves re-authentication in the Android system-browser handoff too.
  const add = useAppConnect(
    "meta",
    complete,
    "/v1/lead-desk/meta/connect-sources",
  );
  const another = useAppConnect(
    "meta",
    complete,
    "/v1/lead-desk/meta/connect-another",
  );
  const pages: MetaPage[] = catalogue?.pages ?? [];
  const running = pages.some((page) => page.backfill?.state === "running");
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load(), 20000);
    return () => clearInterval(timer);
  }, [running, load]);

  const configured = catalogue?.configured === true;
  const summary = failed
    ? "Pages didn't load. Your saved connections are kept."
    : !catalogue
      ? "Checking your connected Pages…"
      : !configured
        ? "Facebook connections are not set up in this environment."
        : !pages.length
          ? "Connect a Facebook account to bring in its Pages' leads."
          : topLine(pages);
  return (
    <div className={styles.stack}>
      <section className={styles.hero} aria-label="Facebook accounts">
        <div className={styles.heroHead}>
          <BrandTile brands={["facebook", "instagram"]} size={44} />
          <div className={styles.heroCopy}>
            <h2>Facebook &amp; Instagram</h2>
            <p>{summary}</p>
          </div>
          <button
            className={styles.iconButton}
            aria-label="Refresh Facebook Pages"
            title="Refresh"
            disabled={!catalogue && !failed}
            onClick={() => void load()}
          >
            <RefreshCw size={18} aria-hidden="true" />
          </button>
        </div>
        {configured && testOnly(pages) ? (
          <span className={styles.status} data-tone="warn" role="status">
            Only Meta test leads so far: no real form has sent a lead yet
          </span>
        ) : null}
        {/* With Pages here, Add Pages sits with each account and another account
            at the end of the list (ux-audit, 2 Nov 2026): the top is one line. */}
        {configured && catalogue && !pages.length ? (
          <div className={styles.chips}>
            <a
              className={styles.primary}
              href="/v1/lead-desk/meta/connect-sources"
              onClick={add}
            >
              <Link2 size={16} aria-hidden="true" />
              Connect Facebook
            </a>
          </div>
        ) : failed ? (
          <div className={styles.chips}>
            <button className={styles.chip} onClick={() => void load()}>
              <RefreshCw size={16} aria-hidden="true" />
              Try again
            </button>
          </div>
        ) : !catalogue ? (
          <Skeleton height={36} />
        ) : null}
      </section>
      {!catalogue && !failed ? (
        <div
          className={styles.stack}
          aria-label="Loading Pages"
          aria-busy="true"
        >
          <Skeleton height={148} />
          <Skeleton height={148} />
        </div>
      ) : null}
      <MetaAccounts
        pages={pages}
        onChanged={() => void load()}
        onAdd={add}
        onAnother={another}
      />
      <div className={styles.more}>
        <details
          className={styles.details}
          onToggle={(event) => setShowOther(event.currentTarget.open)}
        >
          <summary>Other lead sources</summary>
          {showOther ? (
            <div className={styles.otherProviders}>
              <SourcesView
                sandbox={false}
                withoutMeta
                onChanged={() => undefined}
                onImport={() => router.push("/leads?import=file")}
                onImportGoogle={
                  googlePicker
                    ? () => router.push("/leads?import=google")
                    : undefined
                }
              />
            </div>
          ) : null}
        </details>
        <MicrophoneAccess />
      </div>
    </div>
  );
}
