import { duration } from "./call-map-data";
import {
  INTENT_GROUPS,
  intentGroup,
  intentMix,
  ROLE_LABEL,
  type EngineObjects,
} from "./engine-objects-data";
import styles from "./engine-objects.module.css";
import { Badge, Panel, Table } from "../ui/kit";

const pct = (value: number) => `${Math.round(value * 100)}%`;
const ROWS = ["salesperson", "prospect"];

/**
 * What the engine found in one call (owner, 19 Oct: every call becomes data):
 * the measured voice, a timeline of what each segment does in the sale, and the
 * facts with who made them. Operations admins only; quotes are not shown here.
 */
export function EngineObjectsView({ data }: { data: EngineObjects }) {
  const voice = data.voice;
  const total =
    voice?.durationMs ||
    Math.max(1, ...data.segments.map((segment) => segment.endMs));
  const mix = intentMix(data.segments);
  const rows = [
    ...ROWS,
    ...new Set(
      data.segments.map((s) => s.speaker).filter((s) => !ROWS.includes(s)),
    ),
  ];
  return (
    <>
      {voice ? (
        <Panel title="Voice" sub={`measured on the server · ${voice.source}`}>
          {voice.peaks.length ? (
            <svg
              className={styles.wave}
              viewBox={`0 0 ${voice.peaks.length} 40`}
              preserveAspectRatio="none"
              role="img"
              aria-label="Waveform"
            >
              {voice.peaks.map((peak, index) => (
                <rect
                  key={index}
                  x={index + 0.15}
                  width={0.7}
                  y={20 - peak * 19}
                  height={Math.max(0.6, peak * 38)}
                />
              ))}
            </svg>
          ) : null}
          <Table label="Voice by speaker">
            <thead>
              <tr>
                <th scope="col">Speaker</th>
                <th scope="col">Talk share</th>
                <th scope="col">Pace</th>
                <th scope="col">Pitch</th>
                <th scope="col">Loudness</th>
              </tr>
            </thead>
            <tbody>
              {voice.speakers.map((speaker) => (
                <tr key={speaker.label}>
                  <th scope="row">
                    {ROLE_LABEL[speaker.label] ?? speaker.label}
                  </th>
                  <td>
                    <span className={styles.share}>
                      <span style={{ width: pct(speaker.share) }} />
                    </span>
                    {pct(speaker.share)}
                  </td>
                  <td>
                    {speaker.paceWpm !== null
                      ? `${Math.round(speaker.paceWpm)} words/min`
                      : "—"}
                  </td>
                  <td>
                    {speaker.pitchHz !== null
                      ? `${Math.round(speaker.pitchHz)} Hz`
                      : "—"}
                  </td>
                  <td>
                    {speaker.loudnessDbfs !== null
                      ? `${speaker.loudnessDbfs.toFixed(1)} dBFS`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          <p className={styles.note}>
            {voice.pauses.count} pauses over 1.5 s ({voice.pauses.long} over 3
            s, longest {duration(voice.pauses.longestMs) || "0 s"}) ·{" "}
            {duration(voice.overlapMs) || "0 s"} of talking over each other
          </p>
        </Panel>
      ) : null}

      {data.segments.length ? (
        <Panel
          title="Call timeline"
          sub={`${data.segments.length} segments labelled · what each one does in the sale`}
        >
          <div className={styles.timeline} aria-label="Segments over time">
            {rows.map((role) => (
              <div key={role} className={styles.lane}>
                <span className={styles.laneLabel}>
                  {ROLE_LABEL[role] ?? role}
                </span>
                <div className={styles.track}>
                  {data.segments
                    .filter((segment) => segment.speaker === role)
                    .map((segment) => (
                      <span
                        key={segment.segmentId}
                        className={styles.block}
                        data-group={intentGroup(segment.intent)}
                        data-sentiment={segment.sentiment ?? undefined}
                        style={{
                          left: pct(segment.startMs / total),
                          width: `max(2px, ${pct((segment.endMs - segment.startMs) / total)})`,
                        }}
                        title={`${segment.intent.replaceAll("_", " ")} · ${segment.act}${segment.tone ? ` · ${segment.tone}` : ""}`}
                      />
                    ))}
                </div>
              </div>
            ))}
          </div>
          <ul className={styles.legend}>
            {INTENT_GROUPS.map((group) => (
              <li key={group.key}>
                <span
                  className={styles.swatch}
                  data-group={group.key}
                  aria-hidden="true"
                />
                {group.label} <strong>{mix[group.key]}</strong>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel
        title="Facts"
        sub={`${data.facts.length} current · a person's answer always wins`}
      >
        <Table label="Facts">
          <thead>
            <tr>
              <th scope="col">Fact</th>
              <th scope="col">Value</th>
              <th scope="col">Confidence</th>
              <th scope="col">Made by</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.facts.map((fact) => (
              <tr key={fact.objectId}>
                <th scope="row">
                  <span className={styles.category}>
                    {data.categories[fact.category] ?? fact.category}
                  </span>
                  {fact.label}
                </th>
                <td>{fact.display}</td>
                <td>{pct(fact.confidence)}</td>
                <td>
                  <Badge tone={fact.pipeline === "deep" ? "accent" : "neutral"}>
                    {fact.pipeline === "deep"
                      ? fact.replacedFast
                        ? "Deep (updated)"
                        : "Deep"
                      : "Fast"}
                  </Badge>
                  {fact.aiRead ? (
                    <small className={styles.aiRead}> AI read</small>
                  ) : null}
                </td>
                <td>{fact.status.replace("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
    </>
  );
}
