"use client";

import { useState, useSyncExternalStore } from "react";
import { PageHeader, Segmented } from "../../ui/kit";
import { CallCoachingStory } from "../../coaching/call-coaching";
import { parseCoaching } from "../../coaching/coaching-client";
import { CoachingStory } from "../../coaching/coaching-page";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { CoachingWrites, type CoachingWriter } from "../../coaching/sharing-ui";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { TeamCoachingStory } from "../../coaching/team-coaching";
import styles from "../../coaching/coaching.module.css";
import sandbox from "./sandbox.json";
import acSandbox from "./sandbox-team.json";

type View = "call" | "me" | "team";
type Data = "review" | "sandbox";

const noSubscription = () => () => {};

const REACHES = [{ name: "Priya Shah", why: "admin" as const }];

/** The review has no account behind it: a tap shows its flow, nothing is sent. */
const REVIEW_WRITES: CoachingWriter = {
  sharing: async (shared, revision) => ({
    data: { available: true, shared, revision: revision + 1, reaches: REACHES },
    error: null,
  }),
  context: async () => ({ data: true, error: null }),
  feedback: async () => ({ data: true, error: null }),
};

/** Keep the chosen level in the address, so a reload or a link opens it. */
function remember(key: "view" | "data", value: string) {
  const url = new URL(window.location.href);
  url.searchParams.set(key, value);
  window.history.replaceState(window.history.state, "", url);
}

/**
 * Synthetic payloads through the real parsers and screens: the design review
 * set (Dipak clip preview and locked states) and AC Sandbox, built from the
 * synthetic-v1 calls by the server's sandbox adapter (60 fictional reps).
 */
export function CoachingFixture() {
  // ?view=me|team and ?data=sandbox open a level; a tap then takes over.
  const query = new URLSearchParams(
    useSyncExternalStore(
      noSubscription,
      () => window.location.search,
      () => "",
    ),
  );
  const linked = query.get("view");
  const [chosenView, setView] = useState<View | null>(null);
  const [chosenData, setData] = useState<Data | null>(null);
  const view: View =
    chosenView ?? (linked === "me" || linked === "team" ? linked : "call");
  const data: Data =
    chosenData ?? (query.get("data") === "sandbox" ? "sandbox" : "review");
  const set = data === "sandbox" ? acSandbox : sandbox;
  const call = parseCallCoaching(set.call, set.call.submission_id);
  const me = parseCoaching(data === "sandbox" ? acSandbox.rep : sandbox.me);
  const team = parseTeamCoaching(set.team);
  return (
    <CoachingWrites.Provider value={REVIEW_WRITES}>
      <div className={styles.root}>
        <PageHeader
          title="Coaching review"
          context={
            data === "sandbox"
              ? ["AC Sandbox", "3,360 fictional calls, 60 fictional reps"]
              : [
                  "Synthetic sandbox data",
                  "Clip preview and lock states for design review",
                  "Taps here aren’t saved",
                ]
          }
          actions={
            <>
              <Segmented<Data>
                label="Data"
                value={data}
                onChange={(next) => {
                  setData(next);
                  remember("data", next);
                }}
                items={[
                  { key: "review", label: "Design review" },
                  { key: "sandbox", label: "AC Sandbox" },
                ]}
              />
              <Segmented<View>
                label="Coaching level"
                value={view}
                onChange={(next) => {
                  setView(next);
                  remember("view", next);
                }}
                items={[
                  { key: "call", label: "This call" },
                  {
                    key: "me",
                    label: data === "sandbox" ? "One rep" : "My coaching",
                  },
                  { key: "team", label: "Team" },
                ]}
              />
            </>
          }
        />
        {view === "call" && call ? <CallCoachingStory coaching={call} /> : null}
        {view === "me" ? (
          <CoachingStory
            coaching={me}
            readOnly={data === "sandbox"}
            sharing={{
              available: true,
              shared: false,
              revision: 0,
              reaches: REACHES,
            }}
          />
        ) : null}
        {view === "team" && team ? <TeamCoachingStory coaching={team} /> : null}
      </div>
    </CoachingWrites.Provider>
  );
}
