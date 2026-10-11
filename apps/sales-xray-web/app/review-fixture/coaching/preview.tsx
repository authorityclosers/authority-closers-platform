"use client";

import { useEffect, useState } from "react";
import { PageHeader, Segmented } from "../../ui/kit";
import { CallCoachingStory } from "../../coaching/call-coaching";
import { parseCoaching } from "../../coaching/coaching-client";
import { CoachingStory } from "../../coaching/coaching-page";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { TeamCoachingStory } from "../../coaching/team-coaching";
import styles from "../../coaching/coaching.module.css";
import sandbox from "./sandbox.json";
import acSandbox from "./sandbox-team.json";

type View = "call" | "me" | "team";
type Data = "review" | "sandbox";

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
  const [view, setView] = useState<View>("call");
  const [data, setData] = useState<Data>("review");
  // ?view=me|team and ?data=sandbox, read once after the first render.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const wanted = query.get("view");
    if (wanted === "me" || wanted === "team") setView(wanted);
    if (query.get("data") === "sandbox") setData("sandbox");
  }, []);
  const set = data === "sandbox" ? acSandbox : sandbox;
  const call = parseCallCoaching(set.call, set.call.submission_id);
  const me = parseCoaching(data === "sandbox" ? acSandbox.rep : sandbox.me);
  const team = parseTeamCoaching(set.team);
  return (
    <div className={styles.root}>
      <PageHeader
        title="Coaching review"
        context={
          data === "sandbox"
            ? ["AC Sandbox", "3,360 fictional calls, 60 fictional reps"]
            : [
                "Synthetic sandbox data",
                "Clip preview and lock states for design review",
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
            reaches: [{ name: "Priya Shah", why: "admin" }],
          }}
        />
      ) : null}
      {view === "team" && team ? <TeamCoachingStory coaching={team} /> : null}
    </div>
  );
}
