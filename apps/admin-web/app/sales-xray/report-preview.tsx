/**
 * One version's look on a fictional call (orchestrator 20 Oct: "a preview on a
 * fixture call"): which parts, pointers, Prospect sections and Coaching
 * moments show, in which style and detail. Nothing is analysed or spent: the
 * call and its readings are written here. What a version changes that the app
 * does not follow yet is listed under the preview, so a publish promises only
 * what people will see.
 */
import { Badge } from "../ui/kit";
import { valueAt, type Parameter } from "./report-settings-data";
import styles from "./report-preview.module.css";

type Pointer = { id: string; score: number; quote: string; tip: string };

/** The 27 pointers of a fictional rooftop-solar call, in the Report's order. */
export const FIXTURE_POINTERS: readonly Pointer[] = [
  {
    id: "call_opening",
    score: 78,
    quote: "Hi, is this a good time for ten minutes?",
    tip: "Say why you are calling in the first line.",
  },
  {
    id: "purpose_agenda",
    score: 52,
    quote: "So, about the solar thing…",
    tip: "Set a three-point agenda and ask if it works.",
  },
  {
    id: "tone_energy",
    score: 81,
    quote: "That sounds great, tell me more.",
    tip: "Keep this warmth when you reach the price.",
  },
  {
    id: "active_listening",
    score: 74,
    quote: "So the cuts are mostly after 7 pm?",
    tip: "Play back their words before moving on.",
  },
  {
    id: "open_ended_questions",
    score: 61,
    quote: "What made you look at solar now?",
    tip: "Ask one more why before you pitch.",
  },
  {
    id: "enough_questions",
    score: 48,
    quote: "Okay, let me tell you about the panels.",
    tip: "Ask at least five questions before the pitch.",
  },
  {
    id: "prospect_role",
    score: 66,
    quote: "I handle it, but my wife decides too.",
    tip: "Ask how they decide together.",
  },
  {
    id: "needs_challenges",
    score: 72,
    quote: "The evening cuts are the real problem.",
    tip: "Ask how often and how long the cuts last.",
  },
  {
    id: "current_solution",
    score: 55,
    quote: "We have an inverter, it lasts an hour.",
    tip: "Ask what the inverter costs them in hassle.",
  },
  {
    id: "business_impact",
    score: 44,
    quote: "The kids can't study in the dark.",
    tip: "Put a number on the hours lost each week.",
  },
  {
    id: "decision_process",
    score: 39,
    quote: "We'll think about it.",
    tip: "Ask what they need to see to decide.",
  },
  {
    id: "stakeholders",
    score: 42,
    quote: "My wife will want to see it.",
    tip: "Offer a short call with both of them.",
  },
  {
    id: "objections",
    score: 58,
    quote: "It sounds expensive.",
    tip: "Ask what they compare it with first.",
  },
  {
    id: "solution_value",
    score: 63,
    quote: "It pays for itself, mostly.",
    tip: "Tie the value to the evening cuts they named.",
  },
  {
    id: "pricing",
    score: 47,
    quote: "The price depends on the roof.",
    tip: "Give a range and what moves it.",
  },
  {
    id: "competition",
    score: 69,
    quote: "Another company called us last week.",
    tip: "Ask what they liked about the other offer.",
  },
  {
    id: "concerns_check",
    score: 51,
    quote: "Anything else?",
    tip: "Ask: what would stop you from going ahead?",
  },
  {
    id: "next_steps",
    score: 84,
    quote: "Saturday at 11 for the site survey?",
    tip: "Confirm the time in a message straight after.",
  },
  {
    id: "call_control",
    score: 68,
    quote: "Let me come back to the roof in a minute.",
    tip: "Bring the call back to the agenda sooner.",
  },
  {
    id: "question_talk_ratio",
    score: 46,
    quote: "You spoke 64% of the call.",
    tip: "Aim to speak less than half the time.",
  },
  {
    id: "handling_silence",
    score: 71,
    quote: "(paused after the price)",
    tip: "Hold the pause after a big number.",
  },
  {
    id: "professionalism",
    score: 88,
    quote: "Thank you for your time today.",
    tip: "Keep the same courtesy in follow-ups.",
  },
  {
    id: "closing_attitude",
    score: 62,
    quote: "Shall we book the survey?",
    tip: "Ask for the survey with a clear reason.",
  },
  {
    id: "building_rapport",
    score: 79,
    quote: "Same here, the summers are getting worse.",
    tip: "Find one more shared point early.",
  },
  {
    id: "presenting_solution",
    score: 57,
    quote: "The panels go here and the battery there.",
    tip: "Show the evening backup first: it is their problem.",
  },
  {
    id: "creating_value",
    score: 54,
    quote: "You save on the bill too.",
    tip: "Name the hours of power they get back.",
  },
  {
    id: "overall_communication",
    score: 70,
    quote: "Does that make sense?",
    tip: "Check understanding after each part.",
  },
];

const PROSPECT: readonly {
  key: string;
  label: string;
  value: string;
  inferred?: boolean;
}[] = [
  {
    key: "quality",
    label: "Lead quality",
    value: "Warm · ready within a month",
  },
  {
    key: "chips",
    label: "Quick facts",
    value: "Owns the house · evening cuts · two people decide",
  },
  {
    key: "facts",
    label: "What they said",
    value: "The inverter lasts about an hour",
  },
  { key: "problem", label: "Their problem", value: "Power cuts after 7 pm" },
  {
    key: "wants",
    label: "What they want",
    value: "Backup through the evening",
  },
  {
    key: "blockers",
    label: "What holds them back",
    value: "The partner has not seen it yet",
    inferred: true,
  },
  {
    key: "personal",
    label: "Personal notes",
    value: "Prefers calls after 6 pm",
  },
  {
    key: "follow_up",
    label: "Follow-up",
    value: "Send a sample layout by Friday",
  },
  {
    key: "next_action",
    label: "Next action",
    value: "Site survey on Saturday at 11",
  },
  {
    key: "buyer_info",
    label: "Buyer",
    value: "Homeowner, decides with the partner",
    inferred: true,
  },
];

const MOMENTS: readonly string[] = [
  "0:42 · Opened with the reason for the call",
  "2:15 · Asked about the evening cuts",
  "4:30 · Pitched before asking who decides",
  "6:05 · Handled “it sounds expensive” with a question",
  "8:20 · Held the pause after the price",
  "9:40 · Named the partner as a second decider",
  "11:10 · Booked the site survey",
  "12:30 · Confirmed the time out loud",
  "13:05 · Thanked them and set the follow-up",
  "13:40 · Promised a sample layout by Friday",
];

const TONE: Record<string, string> = {
  supportive:
    "Good start: you asked about the evening cuts early. Next time, ask who else decides before you share the price.",
  direct:
    "Ask who else decides before you share the price. You skipped it here, and the call stalled on “we'll think about it”.",
};

const words = (id: string) => {
  const text = id.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

const on = (
  settings: Record<string, unknown>,
  key: string,
  fallback = true,
) => {
  const value = valueAt(settings, key);
  return typeof value === "boolean" ? value : fallback;
};

const pick = (
  settings: Record<string, unknown>,
  key: string,
  fallback: string,
) => {
  const value = valueAt(settings, key);
  return typeof value === "string" ? value : fallback;
};

const count = (
  settings: Record<string, unknown>,
  key: string,
  fallback: number,
) => {
  const value = valueAt(settings, key);
  return typeof value === "number" ? value : fallback;
};

/** The pointers a version shows, in its order, at most its maximum. */
export function shownPointers(settings: Record<string, unknown>): Pointer[] {
  return chosenPointers(settings).slice(
    0,
    count(settings, "report.max_pointers", 27),
  );
}

/** Every pointer a version keeps, in its order (the app shows the rest under Show all). */
export function chosenPointers(settings: Record<string, unknown>): Pointer[] {
  const chosen = valueAt(settings, "report.pointers");
  const ids = Array.isArray(chosen)
    ? chosen.filter((id): id is string => typeof id === "string")
    : FIXTURE_POINTERS.map((pointer) => pointer.id);
  const byId = new Map(
    FIXTURE_POINTERS.map((pointer) => [pointer.id, pointer]),
  );
  return ids
    .map((id) => byId.get(id))
    .filter((pointer): pointer is Pointer => pointer !== undefined);
}

/** What a version changes from version 1 that the app does not follow yet. */
export function notInAppYet(
  settings: Record<string, unknown>,
  baseline: Record<string, unknown>,
  parameters: readonly Parameter[],
): Parameter[] {
  return parameters.filter(
    (parameter) =>
      !parameter.inApp &&
      JSON.stringify(valueAt(settings, parameter.key)) !==
        JSON.stringify(valueAt(baseline, parameter.key)),
  );
}

export function ReportPreview({
  settings,
  baseline,
  parameters,
}: {
  settings: Record<string, unknown>;
  /** Version 1's settings: what "not in the app yet" is measured against. */
  baseline: Record<string, unknown>;
  parameters: readonly Parameter[];
}) {
  const style = pick(settings, "report.style", "guided");
  const detail = pick(settings, "report.complexity", "standard");
  const scores = on(settings, "report.show_scores");
  const evidence = on(settings, "report.show_evidence") && detail !== "simple";
  const tips =
    on(settings, "report.show_how_to_improve") && detail !== "simple";
  const pointers = shownPointers(settings);
  const parts = {
    overview: on(settings, "report.parts.overview"),
    analysis: on(settings, "report.parts.analysis"),
    outcome: on(settings, "report.parts.outcome"),
  };
  const prospect = on(settings, "prospect.enabled");
  const inferred = on(settings, "prospect.show_inferred");
  const coaching = on(settings, "coaching.enabled");
  const moments = on(settings, "coaching.show_moments")
    ? MOMENTS.slice(0, count(settings, "coaching.max_moments", 5))
    : [];
  const pending = notInAppYet(settings, baseline, parameters);
  // As in the app: the first pointers, then a Show all for the rest.
  const more = chosenPointers(settings).length - pointers.length;

  return (
    <div className={styles.preview} aria-label="Preview on a fictional call">
      <p className={styles.call}>
        <strong>Preview · a fictional rooftop-solar call</strong>
        <span>
          Asha (seller) and Ravi (buyer), 14 min · nothing here is real or
          analysed
        </span>
      </p>

      <section className={styles.tab} aria-label="Report preview">
        <h4>
          Report <Badge>{style}</Badge> <Badge>{detail}</Badge>
        </h4>
        {parts.overview ? (
          <div className={styles.part}>
            <b>Overview{scores ? " & Score" : ""}</b>
            {scores ? <span className={styles.score}>64 / 100</span> : null}
            {style === "guided" ? (
              <small>How the call went at a glance, before the detail.</small>
            ) : null}
          </div>
        ) : null}
        {parts.analysis ? (
          <div className={styles.part}>
            <b>
              Detailed Call Analysis{" "}
              <small>
                {pointers.length} of {FIXTURE_POINTERS.length} pointers
              </small>
            </b>
            {style === "scorecard" ? (
              <ul className={styles.scorecard}>
                {pointers.map((pointer) => (
                  <li
                    key={pointer.id}
                    data-low={pointer.score < 50 ? "" : undefined}
                  >
                    <span>{words(pointer.id)}</span>
                    {scores ? <b>{pointer.score}</b> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <ol
                className={
                  style === "compact" ? styles.compact : styles.pointers
                }
              >
                {pointers.map((pointer) => (
                  <li key={pointer.id}>
                    <span className={styles.pointerHead}>
                      {words(pointer.id)}
                      {scores ? <b>{pointer.score}</b> : null}
                    </span>
                    {style !== "compact" && evidence ? (
                      <q>{pointer.quote}</q>
                    ) : null}
                    {style !== "compact" && tips ? (
                      <small>{pointer.tip}</small>
                    ) : null}
                    {style !== "compact" && detail === "expert" ? (
                      <small className={styles.why}>
                        Why it matters:{" "}
                        {pointer.score < 50
                          ? "this held the sale back"
                          : "this moved the buyer forward"}
                        .
                      </small>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
            {more > 0 ? (
              <small className={styles.more}>Show all · {more} more</small>
            ) : null}
          </div>
        ) : null}
        {parts.outcome ? (
          <div className={styles.part}>
            <b>Final Call Outcome</b>
            <span>Site survey booked for Saturday at 11</span>
          </div>
        ) : null}
      </section>

      <section className={styles.tab} aria-label="Prospect preview">
        <h4>
          Prospect{" "}
          <Badge>{pick(settings, "prospect.complexity", "standard")}</Badge>
        </h4>
        {prospect ? (
          <dl className={styles.facts}>
            {PROSPECT.filter(
              (item) =>
                on(settings, `prospect.sections.${item.key}`) &&
                (inferred || !item.inferred),
            ).map((item) => (
              <div key={item.key}>
                <dt>{item.label}</dt>
                <dd>
                  {item.value}
                  {item.inferred ? <Badge>inferred</Badge> : null}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className={styles.off}>The Prospect tab is off.</p>
        )}
      </section>

      <section className={styles.tab} aria-label="Coaching preview">
        <h4>
          Coaching{" "}
          <Badge>{pick(settings, "coaching.complexity", "standard")}</Badge>
        </h4>
        {coaching ? (
          <>
            <p className={styles.tone}>
              {TONE[pick(settings, "coaching.tone", "supportive")] ??
                TONE.supportive}
            </p>
            {moments.length ? (
              <ul className={styles.moments}>
                {moments.map((moment) => (
                  <li key={moment}>{moment}</li>
                ))}
              </ul>
            ) : null}
            {on(settings, "coaching.show_across_calls") ? (
              <small>
                Across the last 10 calls: discovery rose from 48 to 61.
              </small>
            ) : null}
          </>
        ) : (
          <p className={styles.off}>The Coaching tab is off.</p>
        )}
      </section>

      {pending.length ? (
        <p className={styles.pending} role="note">
          <strong>Not in the app yet:</strong>{" "}
          {pending.map((parameter) => parameter.label).join(", ")}. These are
          saved with the version; people see them once each tab adopts them.
        </p>
      ) : null}
    </div>
  );
}
