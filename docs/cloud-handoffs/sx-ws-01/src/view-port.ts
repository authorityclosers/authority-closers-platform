/** Production file: no review imports, discovery, history parsing, storage or side effects. */
export type Display<V> = { kind: "render"; model: V } | { kind: "blocked"; reason: string };
export type ViewPort<V> = (liveModel: V) => Display<V>;
export function workspaceViewPort<V>(liveModel: V): Display<V> {
  return { kind: "render", model: liveModel };
}
