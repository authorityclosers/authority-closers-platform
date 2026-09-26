"use client";

import { createContext, useContext, type ReactNode } from "react";

const ReportReadingContext = createContext(false);
const ReportInlineContext = createContext(false);
export type NavigateToReport = (section: string, reviewPoint?: string) => void;
const ReportNavigationContext = createContext<NavigateToReport | null>(null);

export function useReportReading(): boolean {
  return useContext(ReportReadingContext);
}

/** Full report content can stay inline in either reading or section-tab mode. */
export function useReportInline(): boolean {
  return useContext(ReportInlineContext);
}

export function useReportNavigation(): NavigateToReport | null {
  return useContext(ReportNavigationContext);
}

export function ReportReadingProvider({
  reading,
  inline = reading,
  navigate,
  children,
}: {
  reading: boolean;
  inline?: boolean;
  navigate?: NavigateToReport;
  children: ReactNode;
}) {
  return (
    <ReportNavigationContext.Provider value={navigate ?? null}>
      <ReportReadingContext.Provider value={reading}>
        <ReportInlineContext.Provider value={inline}>
          {children}
        </ReportInlineContext.Provider>
      </ReportReadingContext.Provider>
    </ReportNavigationContext.Provider>
  );
}
