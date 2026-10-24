"use client";

import {
  ArrowRight,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  ChartColumnIncreasing,
  CircleHelp,
  Clock3,
  FileCheck2,
  Gauge,
  Info,
  IndianRupee,
  Lightbulb,
  MapPin,
  Split,
  Star,
  Target,
  TrendingUp,
  TriangleAlert,
  UserRound,
  UsersRound,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { readCallProspect } from "../prospect-report-facts";
import {
  factsFromCallData,
  factsFromCallReview,
  factsFromReport,
  factsFromSavedProspect,
  prospectFacts,
  readCallDataFacts,
  type InsightKind,
  type ProspectFact,
  type ProspectFacts,
} from "../prospect-facts";
import { PROSPECTS_API, editProspectField } from "../prospects-client";
import type { ProspectSummary } from "../prospects-client";
import type { DocumentReportData } from "../report-document-data";
import { useReportLook } from "../report-settings";
import { useWorkspaceAccess } from "../workspace-access";
import { PlayChip, type Select } from "../report-visuals/visuals";
import type { XrayView } from "./model";
import styles from "./prospect.module.css";
import xr from "./xray.module.css";

type Loaded =
  | { callId: string; state: "linked"; prospect: ProspectSummary }
  | { callId: string; state: "none" | "unavailable" };

/** Find the call's prospect; a customer call without one gets its detected prospect. */
async function loadProspect(callId: string, signal: AbortSignal) {
  const linked = await readCallProspect(callId, signal);
  if (linked) return linked;
  const detect = await fetch(`${PROSPECTS_API}/calls/${callId}/detect`, {
    method: "POST",
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: "{}",
    signal,
  });
  if (!detect.ok) return null;
  return readCallProspect(callId, signal);
}

const NO_NAME = "Prospect — name not heard";

/** Save this call as a new prospect (the Report's own create step). */
async function createProspect(callId: string, name: string) {
  const response = await fetch(`${PROSPECTS_API}/calls/${callId}/create`, {
    method: "POST",
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ display_name: name.slice(0, 160) }),
  });
  if (!response.ok) return null;
  return readCallProspect(callId, new AbortController().signal);
}

const DEAL_TONE: Record<string, string> = {
  Won: xr.green,
  Lost: xr.red,
  "Follow-up Set": xr.blue,
  "Decision Pending": xr.amber,
};
const DEAL_WORDS: Record<NonNullable<XrayView["outcome"]["kind"]>, string> = {
  won: "Won",
  lost: "Lost",
  follow_up: "Follow-up Set",
  decision_pending: "Decision Pending",
};
const FIT = {
  strong: "Strong Fit",
  possible: "Possible Fit",
  weak: "Weak Fit",
};
const URGENCY = {
  high: "High Urgency",
  medium: "Medium Urgency",
  low: "Low Urgency",
};
const INSIGHT_ICON: Record<InsightKind, [ReactNode, string]> = {
  business: [<Building2 key="i" />, xr.blue],
  goal: [<TrendingUp key="i" />, xr.green],
  team: [<UsersRound key="i" />, xr.purple],
  investment: [<IndianRupee key="i" />, xr.amber],
  alternative: [<Split key="i" />, xr.red],
  timeline: [<Clock3 key="i" />, xr.amber],
  question: [<CircleHelp key="i" />, xr.blue],
  promise: [<FileCheck2 key="i" />, xr.purple],
  other: [<Info key="i" />, xr.neutral],
};

const UNKNOWN = "Not said in this call";

/** A fact's words, its source as a play chip, and Confirm/Edit when it can be saved. */
function FactValue({
  fact,
  title,
  onSelect,
  save,
}: {
  fact: ProspectFact;
  title: string;
  onSelect?: Select;
  save?: (fact: ProspectFact, value: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const editable = Boolean(save && fact.editKey);
  async function commit(value: string) {
    if (!save || busy) return;
    setBusy(true);
    setError("");
    try {
      await save(fact, value);
      setEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn’t save. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (editing)
    return (
      <form
        className={styles.edit}
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) void commit(draft.trim());
        }}
      >
        <input
          aria-label={title}
          value={draft}
          maxLength={200}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Save
        </button>
        <button type="button" onClick={() => setEditing(false)}>
          Cancel
        </button>
        {error ? <span role="alert">{error}</span> : null}
      </form>
    );
  return (
    <span className={styles.value}>
      <span className={fact.value ? undefined : styles.unknown}>
        {fact.value ?? UNKNOWN}
      </span>
      {fact.evidence[0] ? (
        <PlayChip source={fact.evidence[0]} title={title} onSelect={onSelect} />
      ) : null}
      {fact.basis === "person" ? (
        <span className={styles.yours}>Saved by you</span>
      ) : null}
      {editable ? (
        <span className={styles.actions}>
          {fact.value && fact.basis !== "person" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void commit(fact.value!)}
            >
              Confirm
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setDraft(fact.value ?? "");
              setEditing(true);
            }}
          >
            {fact.value ? "Edit" : "Add"}
          </button>
        </span>
      ) : null}
      {error ? (
        <span className={styles.error} role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}

function Ring({
  score,
  reason,
}: {
  score: number | null;
  reason: string | null;
}) {
  const turn = score ? score / 10 : 0;
  return (
    <figure
      className={styles.ring}
      aria-label="Prospect Quality, the AI’s read"
    >
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle className={styles.ringTrack} cx="60" cy="60" r="52" />
        <circle
          className={styles.ringFill}
          cx="60"
          cy="60"
          r="52"
          pathLength={100}
          strokeDasharray={`${turn * 100} 100`}
        />
      </svg>
      <span className={styles.ringScore}>
        {score ?? "–"}
        <small>/10</small>
      </span>
      <figcaption>
        Prospect Quality
        <span className={styles.aiRead} title={reason ?? undefined}>
          AI&rsquo;s read
        </span>
      </figcaption>
    </figure>
  );
}

function Tile({
  label,
  tone,
  icon,
  fact,
  onSelect,
  save,
}: {
  label: string;
  tone: string;
  icon: ReactNode;
  fact: ProspectFact;
  onSelect?: Select;
  save?: (fact: ProspectFact, value: string) => Promise<void>;
}) {
  return (
    <div className={`${xr.card} ${styles.tile} ${tone}`}>
      <span className={`${xr.disc} ${xr.discLg} ${tone}`}>{icon}</span>
      <div className={styles.tileText}>
        <span className={styles.tileLabel}>{label}</span>
        <FactValue fact={fact} title={label} onSelect={onSelect} save={save} />
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className={styles.page} aria-busy="true" role="status">
      <span className={xr.srOnly}>Reading this prospect’s information…</span>
      <div className={`${xr.card} ${styles.hero} ${styles.shimmer}`} />
      <div className={styles.tiles}>
        {[0, 1, 2, 3, 4, 5].map((n) => (
          <div
            key={n}
            className={`${xr.card} ${styles.tile} ${styles.shimmer}`}
          />
        ))}
      </div>
    </div>
  );
}

function ProspectView({
  facts,
  onSelect,
  save,
  note,
}: {
  facts: ProspectFacts;
  onSelect?: Select;
  save?: (fact: ProspectFact, value: string) => Promise<void>;
  note: ReactNode;
}) {
  // The report settings version: which of the ten sections show, whether the
  // AI's own reads do, and whether sections explain themselves.
  const { prospect: look } = useReportLook();
  const show = look.sections;
  const plain = look.detail === "simple";
  const grid: [string, ReactNode, ProspectFact][] = [
    ["Company", <Building2 key="i" />, facts.company],
    ["Current Revenue", <ChartColumnIncreasing key="i" />, facts.revenue],
    ["Team Size", <UsersRound key="i" />, facts.teamSize],
    ["Industry", <MapPin key="i" />, facts.industry],
  ];
  const headline = [facts.role.value, facts.company.value]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className={styles.page} data-xray-part="prospect">
      <section
        className={`${xr.card} ${styles.remember}`}
        aria-labelledby="prospect-remember"
      >
        <header className={styles.sectionHead}>
          <span className={`${xr.disc} ${xr.blue}`}>
            <UserRound />
          </span>
          <div>
            <h3 id="prospect-remember">Remember Before You Call Again</h3>
            {plain ? null : (
              <p>
                The most important details to help you prepare for your next
                conversation.
              </p>
            )}
          </div>
        </header>
        {note}
        <div
          className={`${xr.card} ${styles.hero}`}
          data-no-ring={show.quality ? undefined : ""}
          data-no-facts={show.facts ? undefined : ""}
        >
          {show.quality ? (
            <Ring score={facts.quality.score} reason={facts.quality.reason} />
          ) : null}
          <div className={styles.who}>
            <h4 className={facts.name.value ? undefined : styles.unknown}>
              {facts.name.value ?? "Name not said in this call"}
            </h4>
            {facts.name.evidence[0] ? (
              <PlayChip
                source={facts.name.evidence[0]}
                title="Name"
                onSelect={onSelect}
              />
            ) : null}
            <p>{headline || "Role and company not said"}</p>
            {show.chips ? (
              <div className={styles.chips}>
                {facts.deal ? (
                  <span
                    className={`${styles.chip} ${DEAL_TONE[facts.deal] ?? xr.neutral}`}
                  >
                    {facts.deal}
                  </span>
                ) : null}
                {look.inferred && facts.urgency.value ? (
                  <span
                    className={`${styles.chip} ${xr.amber}`}
                    title={facts.urgency.reason ?? undefined}
                  >
                    <Zap aria-hidden="true" />
                    {URGENCY[facts.urgency.value]}
                    <span className={styles.aiTag}>AI</span>
                  </span>
                ) : null}
                {look.inferred && facts.fit.value ? (
                  <span
                    className={`${styles.chip} ${facts.fit.value === "weak" ? xr.red : xr.green}`}
                    title={facts.fit.reason ?? undefined}
                  >
                    <Star aria-hidden="true" />
                    {FIT[facts.fit.value]}
                    <span className={styles.aiTag}>AI</span>
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
          {show.facts ? (
            <dl className={styles.facts}>
              {grid.map(([label, icon, fact]) => (
                <div key={label} className={styles.fact}>
                  <span className={`${xr.disc} ${xr.blue}`}>{icon}</span>
                  <div>
                    <dt>{label}</dt>
                    <dd>
                      <FactValue
                        fact={fact}
                        title={label}
                        onSelect={onSelect}
                        save={save}
                      />
                    </dd>
                  </div>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
        <div className={styles.tiles}>
          {show.problem ? (
            <Tile
              label="The Biggest Problem"
              tone={xr.red}
              icon={<Target />}
              fact={facts.problem}
              onSelect={onSelect}
              save={save}
            />
          ) : null}
          {show.wants ? (
            <Tile
              label="What They Want"
              tone={xr.green}
              icon={<ChartColumnIncreasing />}
              fact={facts.wants}
              onSelect={onSelect}
            />
          ) : null}
          {show.blockers ? (
            <Tile
              label="What’s Stopping Them"
              tone={xr.amber}
              icon={<TriangleAlert />}
              fact={facts.stopping}
              onSelect={onSelect}
            />
          ) : null}
          {show.personal ? (
            <Tile
              label="Personal Context / Connection"
              tone={xr.purple}
              icon={<UsersRound />}
              fact={facts.personal}
              onSelect={onSelect}
            />
          ) : null}
          {show.follow_up ? (
            <div
              className={`${xr.card} ${xr.tinted} ${styles.tile} ${xr.green}`}
            >
              <span className={`${xr.disc} ${xr.discLg} ${xr.green}`}>
                <CalendarClock />
              </span>
              <div className={styles.tileText}>
                <span className={styles.tileLabel}>Next follow-up</span>
                {facts.followUp.when ? (
                  <>
                    <span className={styles.when}>{facts.followUp.when}</span>
                    <span className={styles.value}>
                      {facts.followUp.about}
                      {facts.followUp.evidence[0] ? (
                        <PlayChip
                          source={facts.followUp.evidence[0]}
                          title="Next follow-up"
                          onSelect={onSelect}
                        />
                      ) : null}
                    </span>
                  </>
                ) : (
                  <span className={styles.unknown}>
                    No follow-up agreed in this call
                  </span>
                )}
              </div>
            </div>
          ) : null}
          {show.next_action && look.inferred ? (
            <div
              className={`${xr.card} ${xr.tinted} ${styles.tile} ${xr.purple}`}
            >
              <span className={`${xr.disc} ${xr.discLg} ${xr.purple}`}>
                <Lightbulb />
              </span>
              <div className={styles.tileText}>
                <span className={styles.tileLabel}>
                  Suggested next action <span className={styles.aiTag}>AI</span>
                </span>
                <span
                  className={
                    facts.nextAction.value ? styles.value : styles.unknown
                  }
                >
                  {facts.nextAction.value ?? "Appears once the call is scored"}
                </span>
              </div>
              {facts.nextAction.value ? (
                <ArrowRight className={styles.arrow} aria-hidden="true" />
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {show.buyer_info ? (
        <section
          className={`${xr.card} ${styles.more}`}
          aria-labelledby="prospect-more"
        >
          <header className={styles.sectionHead}>
            <span className={`${xr.disc} ${xr.blue}`}>
              <BriefcaseBusiness />
            </span>
            <div>
              <h3 id="prospect-more">Additional Buyer Information</h3>
              {plain ? null : (
                <p>
                  Key insights from the conversation to help you understand the
                  prospect better.
                </p>
              )}
            </div>
          </header>
          {facts.insights.length ? (
            <ul className={styles.insights}>
              {facts.insights.map((item, index) => {
                const [icon, tone] = INSIGHT_ICON[item.kind];
                return (
                  <li key={`${index}-${item.text}`}>
                    <span className={`${xr.disc} ${tone}`}>{icon}</span>
                    <span className={styles.value}>
                      {item.text}
                      <PlayChip
                        source={item.evidence[0]}
                        title="Buyer information"
                        onSelect={onSelect}
                      />
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className={styles.unknown}>
              {facts.reviewed
                ? "The call didn’t give more buyer details."
                : "Appears once the call is scored, usually a few minutes after the report."}
            </p>
          )}
        </section>
      ) : null}
      {plain ? null : (
        <p className={styles.legend}>
          <Gauge aria-hidden="true" /> Quality, urgency, fit and the next action
          are the AI&rsquo;s read of this call. Every other fact was said on the
          call: tap its time to hear it.
        </p>
      )}
    </div>
  );
}

/**
 * 4. Prospect's Information, redesigned (owner, 19 Oct): "Remember Before You
 * Call Again" and "Additional Buyer Information". Facts come from the
 * prospect-facts read model; confirming or editing one saves it to the
 * prospect, where a person's value wins from then on.
 */
export function ProspectPart({
  data,
  callId,
  view,
  onSelect,
}: {
  data: DocumentReportData;
  callId: string | null;
  view: XrayView;
  onSelect?: Select;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Like the outcome read: only a signed-in workspace reads or saves a prospect.
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true && Boolean(access.context);
  useEffect(() => {
    if (!callId || !signedIn) return;
    const controller = new AbortController();
    loadProspect(callId, controller.signal)
      .then((prospect) => {
        if (controller.signal.aborted) return;
        setLoaded(
          prospect
            ? { callId, state: "linked", prospect }
            : { callId, state: "none" },
        );
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setLoaded({ callId, state: "unavailable" });
      });
    return () => controller.abort();
  }, [callId, attempt, signedIn]);

  // The call data engine's facts (v0.65+); none when the server has no engine yet.
  const [callData, setCallData] = useState<{
    callId: string;
    payload: unknown;
  } | null>(null);
  useEffect(() => {
    if (!callId || !signedIn) return;
    const controller = new AbortController();
    readCallDataFacts(callId, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setCallData({ callId, payload });
      })
      .catch(() => {
        // Optional source: the section keeps its other sources.
      });
    return () => controller.abort();
  }, [callId, attempt, signedIn]);
  const engine =
    callData && callData.callId === callId ? callData.payload : null;

  const current = loaded && loaded.callId === callId ? loaded : null;
  const prospect = current?.state === "linked" ? current.prospect : null;
  const facts = useMemo(() => {
    const step = view.outcome.nextSteps.find((item) => item.date) ?? null;
    const open = view.outcome.objections.find((item) => !item.handled);
    const { insights: engineInsights, ...engineFacts } = factsFromCallData(
      engine,
      data.transcript,
    );
    return prospectFacts(
      factsFromSavedProspect(prospect, data.transcript),
      engineFacts,
      factsFromCallReview(data.report?.structure, data.transcript),
      // The review writes whole sentences; the engine's insights fill in after it.
      { insights: engineInsights },
      factsFromReport({
        deal: view.outcome.kind
          ? DEAL_WORDS[view.outcome.kind]
          : view.outcome.label,
        blocker: open ? { text: open.text, sources: open.sources } : null,
        nextAction: view.outcome.suggested,
        nextStep: step
          ? { text: step.text, when: step.date, source: step.source }
          : null,
      }),
    );
  }, [prospect, engine, data.report, data.transcript, view.outcome]);

  if (!data.report) return null;
  if (callId && signedIn && !current) return <Skeleton />;
  const save =
    prospect && prospect.can_edit !== false
      ? async (fact: ProspectFact, value: string) => {
          if (!fact.editKey) return;
          await editProspectField(
            prospect.prospect_id,
            prospect.revision,
            fact.editKey,
            value,
          );
          setAttempt((count) => count + 1);
        }
      : current?.state === "none" && callId
        ? // The first Confirm or Edit saves this call as a prospect, then the fact.
          async (fact: ProspectFact, value: string) => {
            if (!fact.editKey) return;
            const name =
              fact.editKey === "name" ? value : (facts.name.value ?? NO_NAME);
            const created = await createProspect(callId, name);
            if (!created)
              throw new Error("Couldn’t save this prospect. Try again.");
            if (fact.editKey !== "name")
              await editProspectField(
                created.prospect_id,
                created.revision,
                fact.editKey,
                value,
              );
            setAttempt((count) => count + 1);
          }
        : undefined;
  const note =
    current?.state === "linked" || !signedIn ? null : (
      <p className={styles.note}>
        {current?.state === "unavailable"
          ? "The saved prospect couldn’t be read just now, so this shows what this call established."
          : "This call isn’t saved to a prospect yet, so this shows what this call established. Confirm or edit a fact to save it."}{" "}
        <Link href="/prospects">Open Prospects</Link>
      </p>
    );
  return (
    <ProspectView facts={facts} onSelect={onSelect} save={save} note={note} />
  );
}
