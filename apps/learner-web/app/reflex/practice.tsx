"use client";

import { Badge, Empty, List, Panel, Row } from "@ac/ui/kit";
import { BookOpen } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { practiceApi, type PracticeApi } from "../lib/practice-api";
import {
  practiceEngineApi,
  type PracticeEngineApi,
} from "../lib/practice-engine-api";
import { isContentVisible, type SurfaceState } from "../lib/surface-state";
import { practiceHref } from "./data";
import {
  Failure,
  Screen,
  ScreenSkeleton,
  SimulatedState,
  WeekDots,
  styles,
  useRead,
} from "./shared";

const formats = {
  choice: "Next move",
  gap: "Fill the gap",
  match: "Matching pairs",
  build: "Question builder",
  order: "Sequence",
  audio: "Listening",
  branch: "Conversation",
};

export function PracticeHub({
  api = practiceApi,
  engineApi = practiceEngineApi,
  state = "DEFAULT",
}: {
  api?: PracticeApi;
  engineApi?: PracticeEngineApi;
  state?: SurfaceState;
}) {
  const read = useCallback(
    async (signal: AbortSignal) => {
      const [catalog, progress] = await Promise.all([
        api.catalog(signal),
        engineApi.progress(signal),
      ]);
      return { sets: catalog.items, progress };
    },
    [api, engineApi],
  );
  const result = useRead(read, isContentVisible(state));
  const featured = result.data?.sets[0]; // Same daily entry as the existing arcade; issuance stays in the round engine.
  return (
    <Screen state={state} retryHref="/practice">
      {state === "LOADING" || (isContentVisible(state) && result.loading) ? (
        <ScreenSkeleton kind="practice" />
      ) : !isContentVisible(state) ? (
        <SimulatedState state={state} retryHref="/practice" />
      ) : result.error ? (
        <Failure error={result.error} retry={result.retry} />
      ) : (
        <div className={styles.stack}>
          <Panel title="This week">
            <WeekDots
              days={result.data?.progress.actual_practice_days_this_week ?? 0}
            />
          </Panel>
          <Panel title="Today’s set">
            {featured ? (
              <div className={styles.primaryBody}>
                <h3>{featured.title}</h3>
                <p>
                  {formats[featured.kind]}
                  {featured.estimated_minutes
                    ? ` · About ${featured.estimated_minutes} min`
                    : ""}
                </p>
                <Link
                  className={styles.primaryLink}
                  href={practiceHref(featured.id)}
                >
                  Start today’s set
                </Link>
              </div>
            ) : (
              <Empty
                link={Link}
                icon={BookOpen}
                title="New practice sets are on the way."
                action={{ href: "/learning", label: "Keep learning" }}
              />
            )}
          </Panel>
          {result.data?.sets.length ? (
            <Panel title="Available sets">
              <List>
                {result.data.sets.map((set) => (
                  <Row
                    key={set.id}
                    link={Link}
                    title={set.title}
                    href={practiceHref(set.id)}
                    meta={[
                      formats[set.kind],
                      set.estimated_minutes
                        ? `About ${set.estimated_minutes} min`
                        : null,
                    ]}
                  />
                ))}
              </List>
            </Panel>
          ) : null}
          {result.data?.progress.recent_attempts.length ? (
            <Panel title="Recent practice">
              <List>
                {result.data.progress.recent_attempts
                  .slice(0, 5)
                  .map((attempt) => (
                    <Row
                      key={attempt.id}
                      link={Link}
                      title={attempt.title}
                      href={practiceHref(attempt.set_id, attempt.id)}
                      meta={[
                        `${attempt.acknowledged_count}/${attempt.item_count} steps done`,
                      ]}
                      end={
                        <Badge>
                          {attempt.state === "completed"
                            ? "Done"
                            : "In progress"}
                        </Badge>
                      }
                    />
                  ))}
              </List>
            </Panel>
          ) : null}
        </div>
      )}
    </Screen>
  );
}
