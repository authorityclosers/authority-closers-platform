"use client";

import {
  CheckSquare,
  CircleDollarSign,
  HelpCircle,
  Play,
  Square,
  Timer,
  Waves,
} from "lucide-react";
import {
  useMemo,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";

import { voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type { Transcript } from "./report-contract";
import {
  afterPrice,
  confirmedRoles,
  moreSignals,
  promises,
  talkOvers,
  unansweredQuestions,
  type Moment,
} from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import {
  speakerName,
  useSpeakerProfiles,
  voiceStyle,
} from "./speaker-profiles";
import styles from "./call-signals.module.css";
import { RichText } from "./report-entities";
import { useReportDocument } from "./report-reading-context";

const DONE_EVENT = "sales-xray:promises-done";
const doneKey = (callId: string) => `ac.xray.promises-done.v1:${callId}`;

function readDone(callId: string | null): string {
  if (!callId) return "[]";
  try {
    return localStorage.getItem(doneKey(callId)) ?? "[]";
  } catch {
    return "[]";
  }
}

function subscribeDone(notify: () => void) {
  window.addEventListener(DONE_EVENT, notify);
  window.addEventListener("storage", notify);
  return () => {
    window.removeEventListener(DONE_EVENT, notify);
    window.removeEventListener("storage", notify);
  };
}

/** Ticks a promise off (or back on) for this call. */
export function togglePromiseDone(callId: string, id: string) {
  const done = new Set<string>(JSON.parse(readDone(callId)) as string[]);
  if (done.has(id)) done.delete(id);
  else done.add(id);
  try {
    localStorage.setItem(doneKey(callId), JSON.stringify([...done]));
  } catch {
    return;
  }
  window.dispatchEvent(new Event(DONE_EVENT));
}

/** A promise's stable id: its line and exact words. */
export const promiseId = (item: Moment) => `${item.segment.id}:${item.text}`;

/** The promises ticked off for this call, live across the page. */
export function usePromisesDone(callId: string | null): ReadonlySet<string> {
  const raw = useSyncExternalStore(
    subscribeDone,
    () => readDone(callId),
    () => "[]",
  );
  return useMemo(() => new Set<string>(JSON.parse(raw) as string[]), [raw]);
}

/** Removes this call's ticked promises after server deletion succeeds. */
export function clearPromisesDone(callId: string): boolean {
  try {
    localStorage.removeItem(doneKey(callId));
  } catch {
    return false;
  }
  window.dispatchEvent(new Event(DONE_EVENT));
  return true;
}

const seconds = (ms: number) =>
  ms < 1000 ? "under 1 s" : `${Math.round(ms / 1000)} s`;

function PlayLine({
  item,
  onSeek,
  children,
}: {
  item: Moment;
  onSeek: (ms: number) => void;
  children?: ReactNode;
}) {
  return (
    <li className={styles.line}>
      <button
        type="button"
        className={styles.play}
        onClick={() => onSeek(item.start_ms)}
        aria-label={`Play from ${formatClock(item.start_ms)}`}
      >
        <Play size={11} aria-hidden="true" />
        {formatClock(item.start_ms)}
      </button>
      <span className={styles.words}>
        <q>
          <RichText text={item.text} />
        </q>
        {children}
      </span>
    </li>
  );
}

function Card({
  icon,
  title,
  note,
  count,
  children,
  index,
}: {
  icon: ReactNode;
  title: string;
  note?: string;
  count?: number;
  children: ReactNode;
  index: number;
}) {
  return (
    <section className={styles.card} style={{ "--i": index } as CSSProperties}>
      <header>
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
        <h3>{title}</h3>
        {count !== undefined ? <b className={styles.count}>{count}</b> : null}
      </header>
      {note ? <p className={styles.note}>{note}</p> : null}
      {children}
    </section>
  );
}

const Empty = ({ text }: { text: string }) => (
  <p className={styles.empty}>{text}</p>
);

/**
 * Call signals: the prospect's own words, questions that may have gone
 * unanswered, talk-overs, the moment after a price, promises and timing.
 * Measured from the transcript only; every line plays its moment.
 */
export function CallSignals({
  callId,
  transcript,
  onSeek,
}: {
  callId: string | null;
  transcript: Transcript;
  onSeek: (ms: number) => void;
}) {
  const documentView = useReportDocument();
  const { profiles, save, canSave } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const roles = confirmedRoles(
    voices,
    Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
  );
  const done = usePromisesDone(callId);

  const data = useMemo(
    () =>
      roles && {
        unanswered: unansweredQuestions(transcript, roles),
        overs: talkOvers(transcript, roles),
        price: afterPrice(transcript, roles),
        promised: promises(transcript, roles),
        more: moreSignals(transcript, roles),
      },
    // roles is derived from profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, roles?.seller, roles?.prospect],
  );

  const nameOf = (id: string) =>
    speakerName(voices.indexOf(id), profiles[id], accountName);

  if (!roles || !data)
    return (
      <div className={styles.root}>
        <div className={styles.ask}>
          <b>Which voice is the salesperson?</b>
          <p>
            Call signals compare the salesperson and the prospect, so we need to
            know who is who.
          </p>
          <div className={styles.choices}>
            {voices.slice(0, 4).map((id, index) => (
              <button
                key={id}
                type="button"
                disabled={!canSave}
                style={voiceStyle(index)}
                onClick={() => {
                  const other =
                    voices.length === 2
                      ? voices.find((voice) => voice !== id)
                      : undefined;
                  void save({
                    [id]: {
                      name: profiles[id]?.name ?? "",
                      role: "salesperson",
                      icon: profiles[id]?.icon ?? null,
                    },
                    ...(other
                      ? {
                          [other]: {
                            name: profiles[other]?.name ?? "",
                            role: "prospect" as const,
                            icon: profiles[other]?.icon ?? null,
                          },
                        }
                      : {}),
                  });
                }}
              >
                <i aria-hidden="true" />
                {nameOf(id)}
                <small>
                  {(
                    transcript.segments.find((s) => s.speaker_id === id)
                      ?.text ?? ""
                  ).slice(0, 60)}
                </small>
              </button>
            ))}
          </div>
        </div>
      </div>
    );

  const more = data.more;
  const seller = nameOf(roles.seller);
  const prospect = nameOf(roles.prospect);

  return (
    <div className={styles.root}>
      <p className={styles.lead}>
        Measured from the call&apos;s timing and words, with no AI. {seller} is
        the salesperson and {prospect} the prospect. Tap a time to hear it.
      </p>
      <div className={styles.grid}>
        <Card
          index={1}
          icon={<HelpCircle size={16} />}
          title="Questions that may not have been answered"
          note="The prospect asked, and the salesperson did not reply or replied in a few words."
          count={data.unanswered.length}
        >
          {data.unanswered.length ? (
            <ul className={styles.list}>
              {data.unanswered.map((item) => (
                <PlayLine key={item.segment.id} item={item} onSeek={onSeek}>
                  <em className={styles.chip}>{item.reason}</em>
                </PlayLine>
              ))}
            </ul>
          ) : (
            <Empty text="Every question got a reply." />
          )}
        </Card>

        <Card
          index={2}
          icon={<Waves size={16} />}
          title="Talked over them"
          note="The salesperson started while the prospect was still mid-sentence."
          count={data.overs.length}
        >
          {data.overs.length ? (
            <ul className={styles.list}>
              {(documentView ? data.overs : data.overs.slice(0, 6)).map(
                (item) => (
                  <PlayLine key={item.segment.id} item={item} onSeek={onSeek}>
                    <small className={styles.cut}>
                      {prospect} was saying: <q>{item.cut}</q>
                    </small>
                  </PlayLine>
                ),
              )}
            </ul>
          ) : (
            <Empty text="No talk-overs. The prospect got to finish." />
          )}
        </Card>

        <Card
          index={3}
          icon={<CircleDollarSign size={16} />}
          title="After a price or budget mention"
          note="How long the prospect stayed quiet, and what they said next."
          count={data.price.length}
        >
          {data.price.length ? (
            <ul className={styles.list}>
              {data.price.map((item) => (
                <PlayLine key={item.segment.id} item={item} onSeek={onSeek}>
                  <small className={styles.reply}>
                    {item.silence_ms === null ? (
                      "The prospect did not speak again."
                    ) : (
                      <>
                        <b>Silence {seconds(item.silence_ms)}</b>
                        {item.reply ? (
                          <>
                            , then:{" "}
                            <q>
                              <RichText text={item.reply.text} />
                            </q>
                          </>
                        ) : null}
                      </>
                    )}
                    {item.pushback ? (
                      <em className={styles.warn}>sounds like pushback</em>
                    ) : null}
                  </small>
                </PlayLine>
              ))}
            </ul>
          ) : (
            <Empty text="The salesperson did not mention a price, fee or budget." />
          )}
        </Card>

        <Card
          index={4}
          icon={<CheckSquare size={16} />}
          title="Things you said you'd do"
          note="Promises made on the call. Tick them off before the next call. Found by words: listen to check."
          count={data.promised.length}
        >
          {data.promised.length ? (
            <ul className={styles.list}>
              {data.promised.map((item) => {
                const id = promiseId(item);
                const ticked = done.has(id);
                return (
                  <li
                    key={id}
                    className={styles.promise}
                    data-done={ticked ? "" : undefined}
                  >
                    <button
                      type="button"
                      className={styles.tick}
                      aria-pressed={ticked}
                      disabled={!callId}
                      onClick={() => callId && togglePromiseDone(callId, id)}
                      aria-label={ticked ? "Mark as not done" : "Mark as done"}
                    >
                      {ticked ? (
                        <CheckSquare size={16} />
                      ) : (
                        <Square size={16} />
                      )}
                    </button>
                    <button
                      type="button"
                      className={styles.play}
                      onClick={() => onSeek(item.start_ms)}
                      aria-label={`Play from ${formatClock(item.start_ms)}`}
                    >
                      <Play size={11} aria-hidden="true" />
                      {formatClock(item.start_ms)}
                    </button>
                    <q className={styles.words}>
                      <RichText text={item.text} />
                    </q>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty text="No promises found in the salesperson's words." />
          )}
        </Card>

        <Card index={5} icon={<Timer size={16} />} title="More signals">
          <dl className={styles.stats}>
            <div>
              <dt>First question</dt>
              <dd>
                {more.first_question_ms === null
                  ? "None"
                  : formatClock(more.first_question_ms)}
              </dd>
            </div>
            <div>
              <dt>Your questions per 10 min</dt>
              <dd>{more.seller_questions_per_10_min ?? "—"}</dd>
            </div>
            <div>
              <dt>Longest answer to one question</dt>
              <dd>
                {more.longest_answer ? (
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => onSeek(more.longest_answer!.start_ms)}
                  >
                    {seconds(more.longest_answer.length_ms)}
                  </button>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt>Their highest talk share at</dt>
              <dd>
                {more.prospect_peak_ms === null ? (
                  "—"
                ) : (
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => onSeek(more.prospect_peak_ms!)}
                  >
                    {formatClock(more.prospect_peak_ms)}
                  </button>
                )}
              </dd>
            </div>
            <div>
              <dt>Next step came up at</dt>
              <dd>
                {more.next_step_ms === null ? (
                  "Not found"
                ) : (
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => onSeek(more.next_step_ms!)}
                  >
                    {formatClock(more.next_step_ms)}
                  </button>
                )}
              </dd>
            </div>
          </dl>
        </Card>
      </div>
    </div>
  );
}
