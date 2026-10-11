"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  readCallOutcome,
  saveCallOutcome,
  type CallOutcomeBinding,
  type CallOutcomeRecord,
} from "./report-call-outcome-client";
import type { HumanCallOutcome } from "./report-call-outcome-contract";
import { useWorkspaceAccess } from "./workspace-access";

/**
 * The call's person-entered outcome, read once for the whole Report. The
 * Big Picture shows it and offers the one-tap editor; absence is "not
 * recorded", a failed read is "unavailable", never an inferred outcome.
 */
type State =
  | { status: "off" }
  | { status: "loading"; key: string }
  | { status: "unavailable"; key: string }
  | { status: "not_owner"; key: string }
  | {
      status: "ready";
      key: string;
      binding: CallOutcomeBinding;
      record: CallOutcomeRecord;
    };

type Value = {
  state: State;
  save: (value: HumanCallOutcome) => Promise<void>;
  reload: () => Promise<void>;
};

const OFF: Value = {
  state: { status: "off" },
  save: async () => {
    throw new Error("Call outcomes are unavailable here.");
  },
  reload: async () => {},
};

const CallOutcomeContext = createContext<Value>(OFF);

export function useCallOutcome() {
  return useContext(CallOutcomeContext);
}

export function CallOutcomeProvider({
  callId,
  children,
}: {
  /** Only a saved, signed-in call has an outcome; otherwise nothing is read. */
  callId: string | null | undefined;
  children: ReactNode;
}) {
  const access = useWorkspaceAccess();
  const context =
    access?.authenticated && access.status === "ready" ? access.context : null;
  const binding = useMemo<CallOutcomeBinding | null>(
    () =>
      callId && context
        ? {
            callId,
            personId: context.personId,
            tenantId: context.tenantId,
            sessionId: context.sessionId,
          }
        : null,
    [callId, context],
  );
  const key = binding
    ? `${binding.tenantId}:${binding.personId}:${binding.sessionId}:${binding.callId}`
    : null;
  const [state, setState] = useState<State>({ status: "off" });

  useEffect(() => {
    if (!binding || !key) return;
    const controller = new AbortController();
    void readCallOutcome(binding, { signal: controller.signal }).then(
      (result) => {
        if (controller.signal.aborted) return;
        setState(
          result.status === "ready"
            ? {
                status: "ready",
                key,
                binding: result.binding,
                record: result.data,
              }
            : result.status === "not_owner"
              ? { status: "not_owner", key }
              : { status: "unavailable", key },
        );
      },
    );
    return () => controller.abort();
  }, [binding, key]);

  const current = useMemo<State>(
    () =>
      key && state.status !== "off" && state.key === key
        ? state
        : key
          ? { status: "loading", key }
          : { status: "off" },
    [key, state],
  );

  const reload = useCallback(async () => {
    if (!binding || !key) return;
    const result = await readCallOutcome(binding);
    if (result.status === "not_owner") {
      setState({ status: "not_owner", key });
      return;
    }
    if (result.status !== "ready") {
      setState({ status: "unavailable", key });
      throw new Error(result.message);
    }
    setState({
      status: "ready",
      key,
      binding: result.binding,
      record: result.data,
    });
  }, [binding, key]);

  const save = useCallback(
    async (value: HumanCallOutcome) => {
      if (current.status !== "ready") throw new Error("Reload the call first.");
      const result = await saveCallOutcome(
        current.binding,
        current.record,
        value,
      );
      if (result.status !== "saved") throw new Error(result.message);
      setState({
        status: "ready",
        key: current.key,
        binding: result.binding,
        record: result.data,
      });
    },
    [current],
  );

  const value = useMemo<Value>(
    () =>
      current.status === "off"
        ? OFF
        : {
            state: current,
            save,
            reload,
          },
    [current, save, reload],
  );
  return (
    <CallOutcomeContext.Provider value={value}>
      {children}
    </CallOutcomeContext.Provider>
  );
}
