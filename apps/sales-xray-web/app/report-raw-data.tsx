"use client";

import { Download, Play, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { useCallFacts } from "./call-facts";
import {
  numbersHeard,
  priceTalk,
  questionsAsked,
  reportFindings,
  scriptMix,
  voiceStats,
} from "./call-data";
import { formatClock } from "./lightbox/time";
import type { SalesReport, Transcript } from "./report-contract";
import { getShellState } from "./shell/shell-store";
import {
  ROLE_WORDS,
  speakerName,
  useSpeakerProfiles,
} from "./speaker-profiles";
import styles from "./report-raw-data.module.css";

const DIMENSION_WORDS: Record<string, string> = {
  observed: "Seen",
  insufficient_evidence: "Not enough to judge",
  not_applicable: "Does not apply",
  unknown: "Unknown",
  conflicted: "Mixed signals",
};

const KIND_WORDS = {
  money: "Money",
  percent: "Percent",
  time: "Time",
  quantity: "Quantity",
};

function Time({ ms, onSeek }: { ms: number; onSeek: (ms: number) => void }) {
  return (
    <button
      type="button"
      className={styles.time}
      onClick={() => onSeek(ms)}
      aria-label={`Play from ${formatClock(ms)}`}
    >
      <Play size={10} aria-hidden="true" />
      {formatClock(ms)}
    </button>
  );
}

function Block({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section className={styles.block}>
      <h3>
        {title}
        {count !== undefined ? <span>{count}</span> : null}
      </h3>
      {children}
    </section>
  );
}

function download(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function csvCell(value: string | number) {
  const raw = String(value);
  const text =
    typeof value === "string" && /^[=+\-@\t\r]/u.test(value) ? `'${raw}` : raw;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Everything the call and the report contain, as plain lists rather than
 * visuals: the call, the people, every question, every number with a unit,
 * price talk, what the report found and how the report was made. Searchable,
 * and exportable as JSON or CSV. Only real data from this call.
 */
export function ReportRawData({
  callId,
  transcript,
  report,
  durationMs,
  runId,
  onSeek,
}: {
  callId: string | null;
  transcript: Transcript;
  report: SalesReport;
  durationMs: number;
  runId?: string | null;
  onSeek: (ms: number) => void;
}) {
  const [query, setQuery] = useState("");
  const { profiles } = useSpeakerProfiles(callId);
  const { facts } = useCallFacts(callId);
  const accountName = getShellState().profileName;

  const data = useMemo(() => {
    const people = voiceStats(transcript);
    return {
      people,
      questions: questionsAsked(transcript),
      numbers: numbersHeard(transcript),
      price: priceTalk(transcript),
      findings: reportFindings(report),
      scripts: scriptMix(transcript),
      words: people.reduce((sum, person) => sum + person.words, 0),
    };
  }, [transcript, report]);

  const voices = data.people.map((person) => person.id);
  const nameOf = (id: string) =>
    speakerName(voices.indexOf(id), profiles[id], accountName);
  const needle = query.trim().toLocaleLowerCase();
  const matches = (...parts: string[]) =>
    !needle || parts.some((part) => part.toLocaleLowerCase().includes(needle));

  const questions = data.questions.filter((row) =>
    matches(row.text, nameOf(row.voice)),
  );
  const numbers = data.numbers.filter((row) =>
    matches(row.spoken, row.segment.text, nameOf(row.voice)),
  );
  const price = data.price.filter((segment) => matches(segment.text));
  const findings = data.findings.filter((row) => matches(row.title, row.kind));

  function exportJson() {
    download(
      `call-${callId ?? "report"}-raw-data.json`,
      "application/json",
      JSON.stringify(
        {
          call: {
            duration_ms: durationMs,
            lines: transcript.segments.length,
            words: data.words,
            scripts: data.scripts,
          },
          people: data.people.map((person) => ({
            ...person,
            name: nameOf(person.id),
            role: profiles[person.id]?.role ?? null,
          })),
          questions: data.questions.map((row) => ({
            at_ms: row.segment.start_ms,
            speaker: nameOf(row.voice),
            text: row.text,
          })),
          numbers: data.numbers.map((row) => ({
            at_ms: row.segment.start_ms,
            speaker: nameOf(row.voice),
            spoken: row.spoken,
            kind: row.kind,
            meaning: facts.numberLabels[row.id] ?? null,
          })),
          price_talk: data.price.map((segment) => ({
            at_ms: segment.start_ms,
            text: segment.text,
          })),
          findings: data.findings,
          confirmed_facts: facts,
          source: {
            label: report.source_label,
            transcript_revision: transcript.revision,
            timebase: transcript.timebase_id,
            audio_sha256: transcript.source_sha256,
            run_id: runId ?? null,
            review_status: report.review_status,
          },
        },
        null,
        2,
      ),
    );
  }

  function exportCsv() {
    const rows: Array<Array<string | number>> = [
      ["type", "time", "speaker", "text"],
      ...data.questions.map((row) => [
        "question",
        formatClock(row.segment.start_ms),
        nameOf(row.voice),
        row.text,
      ]),
      ...data.numbers.map((row) => [
        `number (${row.kind})`,
        formatClock(row.segment.start_ms),
        nameOf(row.voice),
        `${row.spoken}${facts.numberLabels[row.id] ? ` = ${facts.numberLabels[row.id]}` : ""}`,
      ]),
      ...data.findings.map((row) => [
        `finding (${row.kind})`,
        row.evidence[0] ? formatClock(row.evidence[0].start_ms) : "",
        "",
        row.title,
      ]),
    ];
    download(
      `call-${callId ?? "report"}-raw-data.csv`,
      "text/csv",
      rows.map((row) => row.map(csvCell).join(",")).join("\n"),
    );
  }

  return (
    <div className={styles.raw}>
      <div className={styles.tools}>
        <label className={styles.search}>
          <Search size={14} aria-hidden="true" />
          <input
            value={query}
            placeholder="Search questions, numbers and findings"
            aria-label="Search the raw data"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button type="button" onClick={exportJson}>
          <Download size={14} aria-hidden="true" />
          JSON
        </button>
        <button type="button" onClick={exportCsv}>
          <Download size={14} aria-hidden="true" />
          CSV
        </button>
      </div>

      <Block title="The call">
        <dl className={styles.facts}>
          <div>
            <dt>Length</dt>
            <dd>{formatClock(durationMs)}</dd>
          </div>
          <div>
            <dt>Lines</dt>
            <dd>{transcript.segments.length}</dd>
          </div>
          <div>
            <dt>Words</dt>
            <dd>{data.words.toLocaleString()}</dd>
          </div>
          <div>
            <dt>People</dt>
            <dd>{data.people.length}</dd>
          </div>
          <div>
            <dt>Scripts used</dt>
            <dd>
              Devanagari {Math.round(data.scripts.devanagari * 100)}% · Latin{" "}
              {Math.round(data.scripts.latin * 100)}%
            </dd>
          </div>
        </dl>
      </Block>

      <Block title="People" count={data.people.length}>
        <div className={styles.table} role="table" aria-label="People">
          <div className={styles.headRow} role="row">
            <span role="columnheader">Name</span>
            <span role="columnheader">Talked</span>
            <span role="columnheader">Words</span>
            <span role="columnheader">Questions</span>
            <span role="columnheader">Longest non-stop talk</span>
          </div>
          {data.people.map((person) => (
            <div key={person.id} className={styles.bodyRow} role="row">
              <span role="cell">
                <b>{nameOf(person.id)}</b>
                {profiles[person.id]?.role ? (
                  <small> · {ROLE_WORDS[profiles[person.id].role!]}</small>
                ) : null}
              </span>
              <span role="cell">
                {formatClock(person.talkMs)} · {Math.round(person.share * 100)}%
              </span>
              <span role="cell">{person.words.toLocaleString()}</span>
              <span role="cell">{person.questions}</span>
              <span role="cell">{formatClock(person.longestMs)}</span>
            </div>
          ))}
        </div>
      </Block>

      <Block title="Questions asked" count={questions.length}>
        {questions.length ? (
          <ul className={styles.list}>
            {questions.map((row, index) => (
              <li key={`${row.segment.id}-${index}`}>
                <Time ms={row.segment.start_ms} onSeek={onSeek} />
                <span className={styles.who}>{nameOf(row.voice)}</span>
                <span className={styles.text}>{row.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>No questions match.</p>
        )}
      </Block>

      <Block title="Numbers heard" count={numbers.length}>
        {numbers.length ? (
          <ul className={styles.list}>
            {numbers.map((row) => (
              <li key={row.id}>
                <Time ms={row.segment.start_ms} onSeek={onSeek} />
                <span className={styles.who}>{nameOf(row.voice)}</span>
                <span className={styles.text}>
                  <b>{row.spoken}</b>{" "}
                  <small>
                    {KIND_WORDS[row.kind]}
                    {facts.numberLabels[row.id]
                      ? ` · ${facts.numberLabels[row.id]}`
                      : ""}
                  </small>
                  <q>{row.segment.text}</q>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>
            No numbers said with ₹, lakh, crore, %, days or years.
          </p>
        )}
      </Block>

      <Block title="Price or budget talk" count={price.length}>
        {price.length ? (
          <ul className={styles.list}>
            {price.map((segment) => (
              <li key={segment.id}>
                <Time ms={segment.start_ms} onSeek={onSeek} />
                <span className={styles.who}>
                  {nameOf(segment.speaker_id ?? "unknown")}
                </span>
                <span className={styles.text}>{segment.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>Price or budget never came up.</p>
        )}
      </Block>

      <Block title="What the report found" count={findings.length}>
        <ul className={styles.list}>
          {findings.map((row, index) => (
            <li key={`${row.kind}-${index}`}>
              <span className={styles.kind}>{row.kind}</span>
              <span className={styles.text}>
                {row.title}
                <span className={styles.times}>
                  {row.evidence.map((evidence, at) => (
                    <Time
                      key={`${evidence.segment_id}-${at}`}
                      ms={evidence.start_ms}
                      onSeek={onSeek}
                    />
                  ))}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Skills checked" count={report.dimensions.length}>
        <ul className={styles.list}>
          {report.dimensions.map((dimension) => (
            <li key={dimension.dimension_id}>
              <span className={styles.kind}>
                {DIMENSION_WORDS[dimension.status] ?? dimension.status}
              </span>
              <span className={styles.text}>{dimension.label}</span>
            </li>
          ))}
        </ul>
      </Block>

      <Block title="How this report was made">
        <dl className={styles.facts}>
          <div>
            <dt>Status</dt>
            <dd>
              {report.review_status === "draft_not_dipak_adjudicated"
                ? "Draft coaching, not checked by Dipak"
                : report.review_status}
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{report.source_label}</dd>
          </div>
          <div>
            <dt>Transcript version</dt>
            <dd>{transcript.revision.slice(0, 12)}</dd>
          </div>
          <div>
            <dt>Timing clock</dt>
            <dd>{transcript.timebase_id}</dd>
          </div>
          <div>
            <dt>Audio fingerprint</dt>
            <dd>{transcript.source_sha256.slice(0, 12)}</dd>
          </div>
          {runId ? (
            <div>
              <dt>Analysis run</dt>
              <dd>{runId.slice(0, 8)}</dd>
            </div>
          ) : null}
        </dl>
      </Block>
    </div>
  );
}
