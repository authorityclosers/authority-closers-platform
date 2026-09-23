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

export type PendingAccountIdentity = Readonly<{
  personId: string;
  sessionId: string;
}>;

export type PendingAccountContext = PendingAccountIdentity &
  Readonly<{
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
  stagedFiles: readonly File[];
  accountChanged: boolean;
  selectFile: (file: File) => void;
  addFiles: (files: readonly File[]) => void;
  removeFile: (file: File) => void;
  clearFiles: () => void;
  clearFile: () => void;
  observeAccount: (identity: PendingAccountIdentity | null) => void;
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

function accountKey(identity: PendingAccountIdentity) {
  return JSON.stringify([identity.personId, identity.sessionId]);
}

export function PendingAnalysisProvider({ children }: { children: ReactNode }) {
  const current = useRef<PendingSelection | null>(null);
  const currentFiles = useRef<readonly File[]>([]);
  const boundAccountKey = useRef<string | null>(null);
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [stagedFiles, setStagedFiles] = useState<readonly File[]>([]);
  const [accountChanged, setAccountChanged] = useState(false);

  const clearFiles = useCallback(() => {
    if (current.current) URL.revokeObjectURL(current.current.audioUrl);
    current.current = null;
    currentFiles.current = [];
    setSelection(null);
    setStagedFiles([]);
    setAccountChanged(false);
  }, []);

  const selectFile = useCallback((file: File) => {
    if (!currentFiles.current.includes(file)) {
      const files = [...currentFiles.current, file];
      currentFiles.current = files;
      setStagedFiles(files);
    }
    if (current.current?.file === file) return;
    const boundContextKey = current.current?.boundContextKey ?? null;
    if (current.current) URL.revokeObjectURL(current.current.audioUrl);
    const next: PendingSelection = {
      file,
      audioUrl: URL.createObjectURL(file),
      intentId: crypto.randomUUID(),
      boundContextKey,
    };
    current.current = next;
    setSelection(next);
    setAccountChanged(false);
  }, []);

  const addFiles = useCallback((files: readonly File[]) => {
    const next = [...currentFiles.current];
    for (const file of files) if (!next.includes(file)) next.push(file);
    if (next.length === currentFiles.current.length) return;
    currentFiles.current = next;
    setStagedFiles(next);
    if (!current.current) {
      const selection: PendingSelection = {
        file: next[0],
        audioUrl: URL.createObjectURL(next[0]),
        intentId: crypto.randomUUID(),
        boundContextKey: null,
      };
      current.current = selection;
      setSelection(selection);
    }
    setAccountChanged(false);
  }, []);

  const removeFile = useCallback((file: File) => {
    const index = currentFiles.current.indexOf(file);
    if (index < 0) return;
    const next = currentFiles.current.filter((item) => item !== file);
    currentFiles.current = next;
    setStagedFiles(next);
    if (current.current?.file === file) {
      const boundContextKey = current.current.boundContextKey;
      URL.revokeObjectURL(current.current.audioUrl);
      const replacement = next[index] ?? next[0];
      const selection: PendingSelection | null = replacement
        ? {
            file: replacement,
            audioUrl: URL.createObjectURL(replacement),
            intentId: crypto.randomUUID(),
            boundContextKey,
          }
        : null;
      current.current = selection;
      setSelection(selection);
    }
    setAccountChanged(false);
  }, []);

  const invalidateForAccountChange = useCallback(
    (nextAccountKey: string | null) => {
      const hadFiles = currentFiles.current.length > 0;
      if (current.current) URL.revokeObjectURL(current.current.audioUrl);
      current.current = null;
      currentFiles.current = [];
      boundAccountKey.current = nextAccountKey;
      setSelection(null);
      setStagedFiles([]);
      setAccountChanged(hadFiles);
    },
    [],
  );

  const observeAccount = useCallback(
    (identity: PendingAccountIdentity | null) => {
      const nextAccountKey = identity ? accountKey(identity) : null;
      if (boundAccountKey.current === nextAccountKey) return;
      if (boundAccountKey.current === null && nextAccountKey !== null) {
        boundAccountKey.current = nextAccountKey;
        return;
      }
      invalidateForAccountChange(nextAccountKey);
    },
    [invalidateForAccountChange],
  );

  const bindContext = useCallback(
    (context: PendingAccountContext) => {
      const nextAccountKey = accountKey(context);
      if (
        boundAccountKey.current !== null &&
        boundAccountKey.current !== nextAccountKey
      ) {
        invalidateForAccountChange(nextAccountKey);
        return;
      }
      boundAccountKey.current = nextAccountKey;
      const existing = current.current;
      if (!existing) return;
      const key = contextKey(context);
      if (existing.boundContextKey === key) return;
      if (existing.boundContextKey !== null) {
        invalidateForAccountChange(nextAccountKey);
        return;
      }
      const bound = { ...existing, boundContextKey: key };
      current.current = bound;
      setSelection(bound);
    },
    [invalidateForAccountChange],
  );

  useEffect(
    () => () => {
      if (current.current) URL.revokeObjectURL(current.current.audioUrl);
      current.current = null;
    },
    [],
  );

  return (
    <PendingAnalysisContext.Provider
      value={{
        selection,
        stagedFiles,
        accountChanged,
        selectFile,
        addFiles,
        removeFile,
        clearFiles,
        clearFile: clearFiles,
        observeAccount,
        bindContext,
      }}
    >
      {children}
    </PendingAnalysisContext.Provider>
  );
}

export function usePendingAnalysis() {
  return useContext(PendingAnalysisContext);
}
