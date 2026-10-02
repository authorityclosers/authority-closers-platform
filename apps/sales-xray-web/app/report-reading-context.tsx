"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";

const ReportReadingContext = createContext(false);
const ReportInlineContext = createContext(false);
const ReportDocumentContext = createContext(false);
export type NavigateToReport = (section: string, reviewPoint?: string) => void;
const ReportNavigationContext = createContext<NavigateToReport | null>(null);

export function useReportReading(): boolean {
  return useContext(ReportReadingContext);
}

/** Full report content can stay inline in either reading or section-tab mode. */
export function useReportInline(): boolean {
  return useContext(ReportInlineContext);
}

/** Document output must include supplied content without collapsed controls. */
export function useReportDocument(): boolean {
  return useContext(ReportDocumentContext);
}

/** Asks the report to jump to a section, from outside its sections. */
export const REPORT_GO_EVENT = "sales-xray:report-go";

export function goToReportSection(section: string) {
  window.dispatchEvent(
    new CustomEvent<string>(REPORT_GO_EVENT, { detail: section }),
  );
}

export function useReportNavigation(): NavigateToReport | null {
  return useContext(ReportNavigationContext);
}

/** Lets controls outside the sections (the header's glance tiles) jump. */
function GoListener({ navigate }: { navigate?: NavigateToReport }) {
  useEffect(() => {
    if (!navigate) return;
    const go = (event: Event) => {
      const section = (event as CustomEvent<unknown>).detail;
      if (typeof section === "string") navigate(section);
    };
    window.addEventListener(REPORT_GO_EVENT, go);
    return () => window.removeEventListener(REPORT_GO_EVENT, go);
  }, [navigate]);
  return null;
}

export function ReportReadingProvider({
  reading,
  inline = reading,
  documentView = false,
  navigate,
  children,
}: {
  reading: boolean;
  inline?: boolean;
  documentView?: boolean;
  navigate?: NavigateToReport;
  children: ReactNode;
}) {
  return (
    <ReportNavigationContext.Provider value={navigate ?? null}>
      <GoListener navigate={navigate} />
      <ReportReadingContext.Provider value={reading}>
        <ReportInlineContext.Provider value={inline}>
          <ReportDocumentContext.Provider value={documentView}>
            {children}
          </ReportDocumentContext.Provider>
        </ReportInlineContext.Provider>
      </ReportReadingContext.Provider>
    </ReportNavigationContext.Provider>
  );
}
