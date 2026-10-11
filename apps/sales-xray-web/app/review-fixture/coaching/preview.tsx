"use client";

import { useState } from "react";
import { PageHeader, Segmented } from "../../ui/kit";
import { CallCoachingStory } from "../../coaching/call-coaching";
import { parseCoaching } from "../../coaching/coaching-client";
import { CoachingStory } from "../../coaching/coaching-page";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { TeamCoachingStory } from "../../coaching/team-coaching";
import styles from "../../coaching/coaching.module.css";
import sandbox from "./sandbox.json";

type View = "call" | "me" | "team";

/**
 * Synthetic sandbox payloads through the real parsers and screens, including
 * Dipak clip preview and locked states that no live account returns yet.
 */
export function CoachingFixture() {
  const [view, setView] = useState<View>("call");
  const call = parseCallCoaching(sandbox.call, sandbox.call.submission_id);
  const me = parseCoaching(sandbox.me);
  const team = parseTeamCoaching(sandbox.team);
  return (
    <div className={styles.root}>
      <PageHeader
        title="Coaching review"
        context={[
          "Synthetic sandbox data",
          "Clip preview and lock states for design review",
        ]}
        actions={
          <Segmented<View>
            label="Coaching level"
            value={view}
            onChange={setView}
            items={[
              { key: "call", label: "This call" },
              { key: "me", label: "My coaching" },
              { key: "team", label: "Team" },
            ]}
          />
        }
      />
      {view === "call" && call ? <CallCoachingStory coaching={call} /> : null}
      {view === "me" ? <CoachingStory coaching={me} /> : null}
      {view === "team" && team ? <TeamCoachingStory coaching={team} /> : null}
    </div>
  );
}
