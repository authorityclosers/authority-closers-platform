import { FrameStore, type Selection, type SelectionResult } from "./core.js";
import { parseSelection } from "./commands.js";
import type { Display, ViewPort } from "./view-port.js";
export type ReviewedFrame = Extract<SelectionResult, { kind: "frame" }>;
/** This is a testable gate, NOT proof that the app build actually excludes this file. */
export function assertDevBoundary(env: { nodeEnv: string; phase: string; staticExport: boolean; analysisReadOnly: boolean }): void {
  if (env.nodeEnv !== "development" || env.phase !== "phase-development-server" || env.staticExport || !env.analysisReadOnly)
    throw new Error("review-build-or-policy-blocked");
}
/** Per-canvas adapter, not a global store. Lifetime owner is the local controller.
 * HMR keeps only a selection descriptor; fresh authentication is mandatory on resume.
 * Its output must NEVER be assigned into operational React state.
 */
export function createDevViewPort<V>(store: FrameStore, project: (frame: ReviewedFrame) => V,
  environment: Parameters<typeof assertDevBoundary>[0]): {
  render: ViewPort<V>; select: (input: unknown) => Promise<void>; reset: () => void; descriptor: () => Selection;
} {
  assertDevBoundary(environment);
  let selected: Selection = { mode: "live" }; let generation = 0; let pending = false;
  let failure: string | undefined;
  return {
    async select(input) {
      const next = parseSelection(input); const run = ++generation;
      selected = next; failure = undefined; pending = next.mode !== "live";
      if (next.mode === "live") return;
      try {
        const result = await store.reauthorize(next.frameId);
        if (run !== generation) return;
        if (result.kind !== "authorized") failure = result.reason;
      } catch { if (run === generation) failure = "authorization-unavailable"; }
      finally { if (run === generation) pending = false; }
    },
    render(liveModel): Display<V> {
      if (pending) return { kind: "blocked", reason: "checking-current-access" };
      if (failure) return { kind: "blocked", reason: failure };
      let result: SelectionResult;
      try { result = store.read(selected); } catch { return { kind: "blocked", reason: "clock-or-context-invalid" }; }
      if (result.kind === "live") return { kind: "render", model: liveModel };
      if (result.kind === "unavailable") return { kind: "blocked", reason: result.reason };
      return { kind: "render", model: project(result) };
    },
    reset() { generation++; store.reset(); selected = { mode: "live" }; failure = undefined; pending = false; },
    descriptor() { return structuredClone(selected); },
  };
}
