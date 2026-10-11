"use client";

import { Download, Printer, RefreshCw } from "lucide-react";
import Link from "next/link";
import {
  useContext,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { COMMON, DEAL, DOCUMENT, playLabel } from "./report-copy";
import type { ReportEvidence, Transcript } from "./report-contract";
import type { DocumentReportData } from "./report-document-data";
import {
  reportDocumentModel,
  type DocClip,
  type DocItem,
  type DocPeople,
  type ReportDoc,
} from "./report-document-model";
import { useReportPeople } from "./report-kit";
import { ClipPlayIcon, ClipPlayState } from "./source-waveform";
import { SpeakerProfilesContext } from "./speaker-profiles";
import styles from "./report-document.module.css";

export type DocumentSelect = (evidence: ReportEvidence, title: string) => void;

const EMPTY_TRANSCRIPT = {
  revision: "",
  timebase_id: "",
  duration_ms: 0,
  segments: [],
} as unknown as Transcript;

/** The same names and roles the Report screen uses, never guessed. */
function useDocPeople(
  data: DocumentReportData | undefined,
  callId: string | null | undefined,
): DocPeople {
  const server = useContext(SpeakerProfilesContext);
  const transcript = data?.transcript ?? EMPTY_TRANSCRIPT;
  const people = useReportPeople(callId ?? server?.callId ?? null, transcript);
  const seller = people.roles?.seller ?? null;
  const prospect = people.roles?.prospect ?? null;
  const names = transcript.segments
    .map((segment) => segment.speaker_id)
    .filter((id, index, all): id is string => !!id && all.indexOf(id) === index)
    .map((id) => [id, people.person(id)?.name ?? null] as const);
  const key = JSON.stringify([seller, prospect, names]);
  return useMemo(() => {
    const byId = new Map(names);
    return {
      roles: { seller, prospect },
      speakerName: (id: string) =>
        data?.speakerNames?.[id] ?? byId.get(id) ?? null,
    };
    // `key` carries every input; the people helpers are new each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, data?.speakerNames]);
}

function Play({
  clip,
  title,
  range,
  onSelect,
}: {
  clip: DocClip;
  title: string;
  range?: boolean;
  onSelect?: DocumentSelect;
}) {
  const at = range ? clip.range : clip.at;
  if (!onSelect)
    return (
      <span className={styles.time}>
        {at} · {COMMON.play}
      </span>
    );
  return (
    <ClipPlayState startMs={clip.source.start_ms} endMs={clip.source.end_ms}>
      {(playing) => (
        <button
          type="button"
          className={styles.play}
          aria-pressed={playing}
          aria-label={playLabel(playing, at, title)}
          onClick={() => onSelect(clip.source, title)}
        >
          <ClipPlayIcon playing={playing} size={9} />
          {range ? `${COMMON.play} ${at}` : `${at} · ${COMMON.play}`}
        </button>
      )}
    </ClipPlayState>
  );
}

function Possible() {
  return (
    <span className={styles.possible} title={COMMON.possibleHint}>
      {COMMON.possible}
    </span>
  );
}

function Item({
  item,
  title,
  onSelect,
}: {
  item: DocItem;
  title: string;
  onSelect?: DocumentSelect;
}): ReactNode {
  switch (item.type) {
    case "status":
      return (
        <p className={styles.statusRow}>
          <span className={styles.status} data-tone={item.tone}>
            {item.status}
          </span>
          <span className={styles.origin}>{item.origin}</span>
        </p>
      );
    case "text":
      return (
        <p className={item.strong ? styles.strong : styles.text}>
          {item.text}
          {item.possible ? (
            <>
              {" "}
              <Possible />
            </>
          ) : null}
          {item.clip ? (
            <>
              {" "}
              <Play clip={item.clip} title={title} onSelect={onSelect} />
            </>
          ) : null}
        </p>
      );
    case "label":
      return (
        <p className={styles.label}>
          {item.text}
          {item.possible ? (
            <>
              {" "}
              <Possible />
            </>
          ) : null}
        </p>
      );
    case "list":
      return (
        <ul className={styles.list}>
          {item.items.map((text, index) => (
            <li key={index}>{text}</li>
          ))}
        </ul>
      );
    case "quote":
      return (
        <blockquote className={styles.quote}>
          {item.clip.speaker ? <cite>{item.clip.speaker}</cite> : null}
          <span>“{item.clip.quote}”</span>
        </blockquote>
      );
    case "play":
      return (
        <p className={styles.playRow}>
          <Play
            clip={item.clip}
            title={title}
            range={item.range}
            onSelect={onSelect}
          />
        </p>
      );
    case "metrics":
      return (
        <>
          <dl className={styles.metrics}>
            {item.items.map((metric) => (
              <div key={metric.label}>
                <dd>{metric.value}</dd>
                <dt>
                  {metric.label}
                  {metric.note ? <small>{metric.note}</small> : null}
                </dt>
              </div>
            ))}
          </dl>
          <p className={styles.note}>{item.note}</p>
        </>
      );
    case "timeline":
      return (
        <>
          <ol className={styles.timeline} aria-hidden="true">
            {item.stages.map((stage, index) => (
              <li
                key={`${stage.label}-${index}`}
                data-stage={index % 5}
                style={{ flexGrow: Math.max(0.02, stage.share) }}
              />
            ))}
          </ol>
          <ol className={styles.stages}>
            {item.stages.map((stage, index) => (
              <li key={`${stage.label}-${index}`} data-stage={index % 5}>
                <strong>{stage.label}</strong>
                <span>
                  {stage.from}–{stage.to}
                </span>
              </li>
            ))}
          </ol>
        </>
      );
    case "steps":
      return (
        <ol className={styles.steps}>
          {item.steps.map((step, index) => (
            <li key={index} data-switch={index === 1 || undefined}>
              <span className={styles.stepLabel}>
                {step.label}
                {step.title ? ` · ${step.title}` : ""}
              </span>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      );
    case "card":
      return (
        <div className={styles.card} data-tone={item.tone}>
          {item.kicker ? <p className={styles.kicker}>{item.kicker}</p> : null}
          <p className={styles.cardTitle}>{item.title}</p>
          {item.items.map((inner, index) => (
            <Item
              key={index}
              item={inner}
              title={item.title}
              onSelect={onSelect}
            />
          ))}
        </div>
      );
    case "skills":
      return (
        <div className={styles.skills} role="table" aria-label={title}>
          {item.rows.map((row) => (
            <div key={row.name} className={styles.skill} role="row">
              <p className={styles.skillName} role="rowheader">
                {row.name}
              </p>
              <p role="cell">
                <span
                  className={styles.state}
                  data-tone={row.tone}
                  title={row.meaning ?? undefined}
                >
                  {row.state}
                </span>
              </p>
              <div className={styles.skillBody} role="cell">
                <p className={styles.text}>{row.observation}</p>
                {row.clips.length ? (
                  <p className={styles.plays}>
                    {row.clips.map((clip, index) => (
                      <Play
                        key={`${clip.at}-${index}`}
                        clip={clip}
                        title={row.name}
                        onSelect={onSelect}
                      />
                    ))}
                  </p>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      );
    case "summary":
      return (
        <dl className={styles.summary} aria-label={title}>
          {item.cells.map((cell) => (
            <div key={cell.label}>
              <dt>{cell.label}</dt>
              <dd>{cell.value}</dd>
            </div>
          ))}
        </dl>
      );
  }
}

/** The page: one A4-wide sheet, headings exactly as Dipak's document. */
export function ReportDocumentSheet({
  doc,
  id,
  onSelect,
}: {
  doc: ReportDoc;
  id: string;
  onSelect?: DocumentSelect;
}) {
  return (
    <article className={styles.sheet} aria-labelledby={`${id}-doc-title`}>
      <header className={styles.head}>
        <p className={styles.docKicker}>{doc.kicker}</p>
        <h2 id={`${id}-doc-title`} className={styles.title}>
          {doc.title}
        </h2>
        {doc.facts.length ? (
          <dl className={styles.facts}>
            {doc.facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <p className={styles.draft}>{doc.draftNote}</p>
        <nav className={styles.contents} aria-label={DOCUMENT.contents}>
          <p>{DOCUMENT.contents}</p>
          <ol>
            {doc.sections.map((section) => (
              <li key={section.id}>
                <a href={`#${id}-heading-${section.id}`}>{section.heading}</a>
              </li>
            ))}
          </ol>
        </nav>
      </header>
      {doc.sections.map((section) => (
        <section
          key={section.id}
          className={styles.section}
          aria-labelledby={`${id}-heading-${section.id}`}
          data-document-section={section.id}
        >
          <h3
            id={`${id}-heading-${section.id}`}
            className={styles.pillar}
            tabIndex={-1}
            data-report-mode-section={section.id}
          >
            {section.heading}
          </h3>
          <p className={styles.subtitle}>{section.subtitle}</p>
          {section.parts.map((part, index) => (
            <div key={part.heading ?? index} className={styles.part}>
              {part.heading ? (
                <h4 className={styles.partHeading}>{part.heading}</h4>
              ) : null}
              {part.items.map((item, itemIndex) => (
                <Item
                  key={itemIndex}
                  item={item}
                  title={part.heading ?? section.heading}
                  onSelect={onSelect}
                />
              ))}
            </div>
          ))}
          {section.gaps.length ? (
            <p className={styles.gaps}>
              <span>{COMMON.gapsLead}</span> {section.gaps.join(" · ")}
            </p>
          ) : null}
        </section>
      ))}
      {doc.summary ? (
        <section className={styles.section} aria-label={DOCUMENT.contents}>
          <Item item={doc.summary} title="Report summary" />
        </section>
      ) : null}
      <footer className={styles.foot}>
        <p>{doc.closing}</p>
        <p className={styles.links}>
          <Link href="/prospects">{DEAL.viewProspect}</Link>
          <Link href="/coaching">{DEAL.viewCoaching}</Link>
        </p>
        <p className={styles.footer}>{DOCUMENT.footer}</p>
      </footer>
    </article>
  );
}

/**
 * The Document view: the Report as a clean, printable page that mirrors
 * Dipak's document, with Print and a Word file built from the same blocks.
 */
export function ReportDocument({
  data,
  id,
  textSize,
  section,
  callId,
  onSelect,
}: {
  data?: DocumentReportData;
  id: string;
  textSize: string;
  section?: string;
  callId?: string | null;
  onSelect?: DocumentSelect;
}) {
  const people = useDocPeople(data, callId);
  const doc = useMemo(() => {
    if (!data?.report) return null;
    try {
      return reportDocumentModel(data, people);
    } catch {
      // A malformed older report shows a quiet note, never a broken page.
      return "unavailable" as const;
    }
  }, [data, people]);
  const [word, setWord] = useState<"idle" | "busy" | "failed">("idle");

  useEffect(() => {
    if (doc && doc !== "unavailable" && section)
      document
        .getElementById(`${id}-heading-${section}`)
        ?.scrollIntoView?.({ block: "start" });
  }, [doc, id, section]);

  async function downloadWord() {
    if (!data?.report || word === "busy") return;
    setWord("busy");
    try {
      const { createReportDocx, reportDocxFilename } = await import(
        "./report-docx"
      );
      const blob = await createReportDocx(data, people);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = reportDocxFilename(data.title);
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
      setWord("idle");
    } catch {
      setWord("failed");
    }
  }

  return (
    <div
      className={styles.document}
      data-document-export
      style={{ "--doc-scale": Number(textSize) / 100 || 1 } as CSSProperties}
    >
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.action}
          onClick={() => window.print()}
          disabled={!doc || doc === "unavailable"}
        >
          <Printer aria-hidden="true" /> {DOCUMENT.print}
        </button>
        <button
          type="button"
          className={styles.action}
          data-primary
          onClick={() => void downloadWord()}
          disabled={!doc || doc === "unavailable" || word === "busy"}
          aria-busy={word === "busy" || undefined}
        >
          <Download aria-hidden="true" />
          {word === "busy" ? DOCUMENT.preparing : DOCUMENT.download}
        </button>
        {word === "failed" ? (
          <p className={styles.failed} role="alert">
            {DOCUMENT.wordFailed}
            <button
              type="button"
              className={styles.retry}
              onClick={() => void downloadWord()}
            >
              <RefreshCw aria-hidden="true" /> {COMMON.tryAgain}
            </button>
          </p>
        ) : null}
      </div>
      <div
        className={styles.canvas}
        role="region"
        aria-label={DOCUMENT.regionLabel}
      >
        {doc === "unavailable" ? (
          <p className={styles.unavailable} role="status">
            {COMMON.reportFailed}
          </p>
        ) : doc ? (
          <ReportDocumentSheet doc={doc} id={id} onSelect={onSelect} />
        ) : null}
      </div>
    </div>
  );
}
