"use client";

/**
 * Every object the engine ever made for this call, dense: type, what it says,
 * confidence, basis, which read made it, whether it is still current, and what
 * people decided about it. Filter by type, state or words.
 */
import { useMemo, useState } from "react";

import { Badge, Table, type Tone } from "../ui/kit";
import {
  objectFacets,
  type DetailObject,
  type ObjectState,
} from "./call-detail-data";
import styles from "./call-detail.module.css";

const STATE_TONE: Record<ObjectState, Tone> = {
  current: "good",
  superseded: "neutral",
  retracted: "warn",
  erased: "bad",
};

const STATE_LABEL: Record<ObjectState, string> = {
  current: "Current",
  superseded: "Superseded",
  retracted: "Retracted",
  erased: "Erased",
};

const words = (value: string) => value.replaceAll("_", " ");

export function ObjectsTable({
  objects,
}: {
  objects: readonly DetailObject[];
}) {
  const facets = useMemo(() => objectFacets(objects), [objects]);
  const [type, setType] = useState("");
  const [state, setState] = useState<ObjectState | "">("current");
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return objects.filter(
      (object) =>
        (!type || object.type === type) &&
        (!state || object.state === state) &&
        (!needle ||
          `${object.display} ${object.category} ${object.type} ${object.basis ?? ""}`
            .toLowerCase()
            .includes(needle)),
    );
  }, [objects, type, state, query]);

  return (
    <>
      <div className={styles.filters}>
        <select
          aria-label="Object type"
          value={type}
          onChange={(event) => setType(event.target.value)}
        >
          <option value="">All types ({objects.length})</option>
          {facets.types.map(([name, count]) => (
            <option key={name} value={name}>
              {words(name)} ({count})
            </option>
          ))}
        </select>
        <span className={styles.chips} role="group" aria-label="State">
          {(["", "current", "superseded", "retracted", "erased"] as const).map(
            (value) => {
              const count = value
                ? (facets.states.find(([name]) => name === value)?.[1] ?? 0)
                : objects.length;
              return (
                <button
                  key={value || "all"}
                  type="button"
                  aria-pressed={state === value}
                  onClick={() => setState(value)}
                >
                  {value ? STATE_LABEL[value] : "All"} {count}
                </button>
              );
            },
          )}
        </span>
        <input
          type="search"
          aria-label="Find in objects"
          placeholder="Find…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <span className={styles.count}>{shown.length} shown</span>
      </div>
      <Table label="Objects">
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col">What it says</th>
            <th scope="col" data-num="">
              Confidence
            </th>
            <th scope="col">Basis</th>
            <th scope="col">Made by</th>
            <th scope="col">State</th>
            <th scope="col">Decisions</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((object) => (
            <tr key={object.objectId}>
              <th scope="row" className={styles.type}>
                <small>{words(object.category || object.type)}</small>
                {words(object.type)}
              </th>
              <td className={styles.display}>{object.display || "—"}</td>
              <td data-num="">
                {object.confidence === null
                  ? "—"
                  : `${Math.round(object.confidence * (object.confidence <= 1 ? 100 : 1))}%`}
              </td>
              <td className={styles.muted}>{object.basis ?? "—"}</td>
              <td className={styles.muted}>
                {[object.pipeline, object.version]
                  .filter(Boolean)
                  .join(" · ") || "—"}
              </td>
              <td>
                <Badge tone={STATE_TONE[object.state]}>
                  {STATE_LABEL[object.state]}
                </Badge>
              </td>
              <td className={styles.muted}>
                {object.decisions.length
                  ? object.decisions
                      .map((item) =>
                        [item.decision, item.actor]
                          .filter(Boolean)
                          .join(" by "),
                      )
                      .join("; ")
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {shown.length ? null : (
        <p className={styles.none}>No objects match these filters.</p>
      )}
    </>
  );
}
