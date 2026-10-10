"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Download, RefreshCw } from "lucide-react";
import type { DocumentReportData } from "./report-document-data";
import styles from "./report-document.module.css";

/** One generated Blob owns both the rendered document and its download URL. */
export function ReportDocument({
  data,
  id,
  textSize,
  section,
}: {
  data?: DocumentReportData;
  id: string;
  textSize: string;
  section?: string;
}) {
  const source = JSON.stringify(data ?? {});
  const host = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    source: string;
    url?: string;
    filename?: string;
    failed?: boolean;
  }>();
  const ready = result?.source === source && result.url;
  const failed = result?.source === source && result.failed;

  useEffect(() => {
    const element = viewport.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth)
        setFit(Math.min(1, element.clientWidth / (793.7 + 40)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let url: string | undefined;
    const body = document.createElement("div");
    const sheetStyles = document.createElement("div");
    host.current?.replaceChildren();
    async function prepare() {
      const [
        { createReportDocx, reportDocxFilename, DOCUMENT_CHAPTERS },
        { renderAsync },
      ] = await Promise.all([import("./report-docx"), import("docx-preview")]);
      const data: DocumentReportData = JSON.parse(source);
      const blob = await createReportDocx(data);
      if (cancelled) return;
      await renderAsync(blob, body, sheetStyles, {
        className: "report-docx",
        inWrapper: true,
        breakPages: true,
        renderHeaders: true,
        renderFooters: true,
        ignoreWidth: false,
        ignoreHeight: false,
        renderAltChunks: false,
      });
      if (cancelled) return;
      // Word bookmarks connect existing section navigation to the actual DOCX.
      for (const chapter of DOCUMENT_CHAPTERS) {
        const anchor = body.querySelector(`[id="${chapter.id}"]`);
        const heading = anchor?.closest("p");
        if (!heading) continue;
        heading.id = `${id}-heading-${chapter.id}`;
        heading.tabIndex = -1;
        heading.dataset.reportModeSection = chapter.id;
        heading.setAttribute("role", "heading");
        heading.setAttribute("aria-level", "1");
      }
      url = URL.createObjectURL(blob);
      host.current?.replaceChildren(sheetStyles, body);
      setResult({ source, url, filename: reportDocxFilename(data.title) });
    }
    void prepare().catch(() => {
      if (!cancelled) setResult({ source, failed: true });
    });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [source, id, attempt]);

  useEffect(() => {
    if (ready && section)
      document
        .getElementById(`${id}-heading-${section}`)
        ?.scrollIntoView?.({ block: "start" });
  }, [ready, id, section]);

  return (
    <div className={styles.document} data-document-export>
      <div className={styles.actions}>
        {ready ? (
          <a
            className={styles.download}
            href={ready}
            download={result.filename}
          >
            <Download aria-hidden="true" /> Download .docx
          </a>
        ) : (
          <button className={styles.download} type="button" disabled>
            <Download aria-hidden="true" /> Download .docx
          </button>
        )}
        <span>A4 · {textSize}% zoom</span>
      </div>
      {!ready && (
        <p role={failed ? "alert" : "status"}>
          {failed
            ? "The document could not be prepared. Please try again."
            : "Preparing your document…"}
          {failed && (
            <button
              type="button"
              className={styles.retry}
              onClick={() => {
                setResult(undefined);
                setAttempt((value) => value + 1);
              }}
            >
              <RefreshCw aria-hidden="true" /> Try again
            </button>
          )}
        </p>
      )}
      <div
        ref={viewport}
        className={styles.scroll}
        role="region"
        aria-label="Sales Xray document preview"
        tabIndex={0}
        hidden={!ready}
      >
        <div
          ref={host}
          className={styles.pages}
          style={
            {
              "--document-zoom": Number(textSize) / 100,
              "--document-fit": fit,
            } as CSSProperties
          }
        />
      </div>
    </div>
  );
}
