"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type PendingAccountContext = Readonly<{
  personId: string;
  sessionId: string;
  tenantId: string;
}>;

export type PendingSelection = Readonly<{
  file: File;
  audioUrl: string;
  intentId: string;
  boundContextKey: string | null;
}>;

type PendingAnalysisValue = Readonly<{
  selection: PendingSelection | null;
  accountChanged: boolean;
  selectFile: (file: File) => void;
  clearFile: () => void;
  bindContext: (context: PendingAccountContext) => void;
}>;

const PendingAnalysisContext = createContext<PendingAnalysisValue | null>(null);

function contextKey(context: PendingAccountContext) {
  return JSON.stringify([
    context.personId,
    context.sessionId,
    context.tenantId,
  ]);
}

export function PendingAnalysisProvider({ children }: { children: ReactNode }) {
  const current = useRef<PendingSelection | null>(null);
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [accountChanged, setAccountChanged] = useState(false);

  const clearFile = useCallback(() => {
    if (current.current) URL.revokeObjectURL(current.current.audioUrl);
    current.current = null;
    setSelection(null);
    setAccountChanged(false);
  }, []);

  const selectFile = useCallback((file: File) => {
    if (current.current) URL.revokeObjectURL(current.current.audioUrl);
    const next: PendingSelection = {
      file,
      audioUrl: URL.createObjectURL(file),
      intentId: crypto.randomUUID(),
      boundContextKey: null,
    };
    current.current = next;
    setSelection(next);
    setAccountChanged(false);
  }, []);

  const bindContext = useCallback((context: PendingAccountContext) => {
    const existing = current.current;
    if (!existing) return;
    const key = contextKey(context);
    if (existing.boundContextKey === key) return;
    if (existing.boundContextKey !== null) {
      URL.revokeObjectURL(existing.audioUrl);
      current.current = null;
      setSelection(null);
      setAccountChanged(true);
      return;
    }
    const bound = { ...existing, boundContextKey: key };
    current.current = bound;
    setSelection(bound);
  }, []);

  useEffect(
    () => () => {
      if (current.current) URL.revokeObjectURL(current.current.audioUrl);
      current.current = null;
    },
    [],
  );

  return (
    <PendingAnalysisContext.Provider
      value={{ selection, accountChanged, selectFile, clearFile, bindContext }}
    >
      {children}
    </PendingAnalysisContext.Provider>
  );
}

export function usePendingAnalysis() {
  return useContext(PendingAnalysisContext);
}
