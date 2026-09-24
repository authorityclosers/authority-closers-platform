"use client";

import { createContext, useContext, type ReactNode } from "react";

const ReportReadingContext = createContext(false);
export type NavigateToReport = (section: string, reviewPoint?: string) => void;
const ReportNavigationContext = createContext<NavigateToReport | null>(null);

export function useReportReading(): boolean {
  return useContext(ReportReadingContext);
}

export function useReportNavigation(): NavigateToReport | null {
  return useContext(ReportNavigationContext);
}

export function ReportReadingProvider({
  reading,
  navigate,
  children,
}: {
  reading: boolean;
  navigate?: NavigateToReport;
  children: ReactNode;
}) {
  return (
    <ReportNavigationContext.Provider value={navigate ?? null}>
      <ReportReadingContext.Provider value={reading}>
        {children}
      </ReportReadingContext.Provider>
    </ReportNavigationContext.Provider>
  );
}
