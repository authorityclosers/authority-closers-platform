/**
 * ₹/min now (owner, 22 Oct 2026): one environment's cost per audio minute today, over 24
 * hours and over 7 days, against the ₹0.40 and ₹0.10 targets, with how fresh the numbers
 * are and the rupee rate they use. Home shows the three numbers; Health adds full reports
 * against short calls and the split by pipeline version.
 */
import Link from "next/link";

import { Panel, Table, Why } from "../ui/kit";
import { rateWords } from "./cost-data";
import {
  ageWords,
  groupWords,
  isStale,
  meterTone,
  perMinuteWords,
  scaleOf,
  type CostMeter as Meter,
  type MeterWindow,
} from "./meter-data";
import styles from "./cost-meter.module.css";

const ENVIRONMENT_WORDS: Record<string, string> = {
  production: "production",
  staging: "staging",
  development: "dev",
};

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

const when = (iso: string) => {
  const moment = Date.parse(iso);
  return Number.isNaN(moment) ? "–" : DAY.format(moment);
};

function Scale({
  value,
  targets,
}: {
  value: number | null;
  targets: number[];
}) {
  const scale = scaleOf(value, targets);
  return (
    <span className={styles.scale} aria-hidden="true">
      {scale.value !== null ? (
        <i
          className={styles.fill}
          data-tone={meterTone(value, targets)}
          style={{ width: `${scale.value}%` }}
        />
      ) : null}
      {scale.targets.map((mark) => (
        <b
          key={mark.target}
          className={styles.mark}
          style={{ left: `${mark.at}%` }}
        >
          <span>{perMinuteWords(mark.target).replace("/min", "")}</span>
        </b>
      ))}
    </span>
  );
}

function WindowTile({
  slot,
  targets,
  detail,
}: {
  slot: MeterWindow;
  targets: number[];
  detail: boolean;
}) {
  const value = slot.allIn.perMinute;
  const tone = meterTone(value, targets);
  return (
    <section
      className={styles.window}
      aria-label={`${slot.label}: ${perMinuteWords(value)}`}
    >
      <span className={styles.label}>{slot.label}</span>
      <strong className={styles.value} data-tone={tone}>
        {perMinuteWords(value)}
      </strong>
      <Scale value={value} targets={targets} />
      <span className={styles.line}>
        {slot.allIn.calls ? groupWords(slot.allIn) : "No analysed calls yet"}
      </span>
      {detail ? (
        <dl className={styles.split}>
          <div>
            <dt>Full reports</dt>
            <dd>
              {perMinuteWords(slot.fullReports.perMinute)}{" "}
              <small>{groupWords(slot.fullReports)}</small>
            </dd>
          </div>
          <div>
            <dt>Short or data-only</dt>
            <dd>
              {perMinuteWords(slot.short.perMinute)}{" "}
              <small>{groupWords(slot.short)}</small>
            </dd>
          </div>
          <div>
            <dt>Recorded, not analysed</dt>
            <dd>
              <small>
                {slot.notAnalysed.calls}{" "}
                {slot.notAnalysed.calls === 1 ? "call" : "calls"} ·{" "}
                {slot.notAnalysed.audioMinutes} min · no cost
              </small>
            </dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}

export function CostMeter({
  meter,
  detail = false,
}: {
  meter: Meter;
  detail?: boolean;
}) {
  const where = ENVIRONMENT_WORDS[meter.environment] ?? meter.environment;
  const stale = isStale(meter.ageSeconds);
  const targets = meter.targets;
  return (
    <Panel
      title={`₹/min now · ${where}`}
      sub={`${ageWords(meter.ageSeconds)} · rupees at ${rateWords(meter.fx)}`}
      tools={
        <Why
          detail={`Each call's whole cost (transcription, facts, report, pointer review, call data and any re-runs) over its audio minutes, counted by when it was first transcribed; canary, QA and synthetic calls never count. All-in is full reports and short calls together. Calls only recorded and audio-checked cost nothing and are counted apart. Targets: ₹${targets.join(" and ₹")}/min. List-price estimates from the ${where} export, refreshed every 5 minutes; not a bill.`}
        />
      }
    >
      {!meter.available ? (
        <p className={styles.note}>
          The {where} export isn&rsquo;t in the metrics store yet, so there is
          nothing to measure.
        </p>
      ) : (
        <>
          {stale ? (
            <p className={styles.note} data-tone="warn">
              These numbers are from{" "}
              {ageWords(meter.ageSeconds).replace("updated ", "")}: the
              collector may have stopped.
            </p>
          ) : null}
          <div className={styles.windows}>
            {meter.windows.map((slot) => (
              <WindowTile
                key={slot.key}
                slot={slot}
                targets={targets}
                detail={detail}
              />
            ))}
          </div>
          {detail && meter.byVersion.length ? (
            <Table label="Cost per minute by pipeline version, last 7 days">
              <thead>
                <tr>
                  <th scope="col">Pipeline version</th>
                  <th scope="col" data-num="">
                    Calls
                  </th>
                  <th scope="col" data-num="">
                    Full reports
                  </th>
                  <th scope="col" data-num="">
                    Audio min
                  </th>
                  <th scope="col" data-num="">
                    ₹/min
                  </th>
                  <th scope="col">First → last</th>
                </tr>
              </thead>
              <tbody>
                {meter.byVersion.map((row) => (
                  <tr key={row.id}>
                    <th scope="row">
                      <code className={styles.version}>{row.label}</code>
                    </th>
                    <td data-num="">{row.calls}</td>
                    <td data-num="">{row.fullReports}</td>
                    <td data-num="">{row.audioMinutes}</td>
                    <td data-num="">
                      <span
                        data-tone={meterTone(row.perMinute, targets)}
                        className={styles.rate}
                      >
                        {perMinuteWords(row.perMinute)}
                      </span>
                    </td>
                    <td>
                      {when(row.firstAt)} → {when(row.lastAt)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
          {!detail ? (
            <Link href="/health#cost-meter" className={styles.more}>
              Full reports, short calls and versions
            </Link>
          ) : null}
        </>
      )}
    </Panel>
  );
}
