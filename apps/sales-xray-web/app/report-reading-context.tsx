"use client";

import { createContext, useContext, type ReactNode } from "react";

const ReportReadingContext = createContext(false);

export function useReportReading(): boolean {
  return useContext(ReportReadingContext);
}

export function ReportReadingProvider({
  reading,
  children,
}: {
  reading: boolean;
  children: ReactNode;
}) {
  return (
    <ReportReadingContext.Provider value={reading}>
      {children}
    </ReportReadingContext.Provider>
  );
}
