"use client";

import { Badge, Empty, List, Panel, Row } from "@ac/ui/kit";
import { BookOpen, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import {
  type LearnerApi,
  type LearningActivityResponse,
  type LearningModuleResponse,
} from "../lib/learner-api";
import { firstActionableActivity } from "../lib/next-learning-action";
import { isContentVisible, type SurfaceState } from "../lib/surface-state";
import {
  courseHref,
  kindLabel,
  learnerApi,
  readCourse,
  stateLabel,
} from "./data";
import {
  Artwork,
  Failure,
  KindIcon,
  Progress,
  Screen,
  ScreenSkeleton,
  SimulatedState,
  styles,
  useRead,
} from "./shared";

function lockReason(activity: LearningActivityResponse) {
  if (activity.explanation.missing_module_ids.length)
    return "Finish the earlier required modules to unlock.";
  return "Finish the earlier required steps to unlock.";
}
function moduleState(module: LearningModuleResponse) {
  const states = module.activities.map((activity) =>
    activity.state.toLowerCase(),
  );
  if (states.length && states.every((state) => state === "completed"))
    return "completed";
  if (!states.length) return "unavailable";
  if (states.every((state) => state === "locked")) return "locked";
  if (
    states.some((state) =>
      ["in_progress", "completed", "awaiting_review"].includes(state),
    )
  )
    return "in_progress";
  return "available";
}

export function CourseScreen({
  slug,
  moduleId,
  api = learnerApi,
  state = "DEFAULT",
}: {
  slug: string;
  moduleId?: string;
  api?: LearnerApi;
  state?: SurfaceState;
}) {
  const read = useCallback(
    (signal: AbortSignal) => readCourse(api, slug, signal),
    [api, slug],
  );
  const result = useRead(read, isContentVisible(state));
  const learning = result.data;
  const selected = learning?.modules.find((item) => item.id === moduleId);
  const next = learning ? firstActionableActivity(learning) : undefined;
  const href = courseHref(slug);
  return (
    <Screen state={state} retryHref={href}>
      {state === "LOADING" || (isContentVisible(state) && result.loading) ? (
        <ScreenSkeleton kind={moduleId ? "module" : "course"} />
      ) : !isContentVisible(state) ? (
        <SimulatedState
          state={state}
          retryHref={
            moduleId ? `${href}/module/${encodeURIComponent(moduleId)}` : href
          }
        />
      ) : result.error ? (
        <Failure error={result.error} retry={result.retry} />
      ) : !learning || (moduleId && !selected) ? (
        <Empty
          link={Link}
          icon={BookOpen}
          title="This course or module isn’t available."
          action={{ href: "/learning", label: "My courses" }}
        />
      ) : selected ? (
        <div className={styles.stack}>
          <Link href={href} className={styles.quietLink}>
            Back to course
          </Link>
          <h2>{selected.title}</h2>
          <Panel title="Steps">
            <List label="Module steps">
              {selected.activities.map((activity) => {
                const locked = activity.state.toLowerCase() === "locked";
                const openable =
                  activity.state.toLowerCase() === "completed" ||
                  (!locked &&
                    (activity.allowed_actions.length > 0 ||
                      activity.state.toLowerCase() === "awaiting_review"));
                return (
                  <Row
                    key={activity.id}
                    link={Link}
                    icon={
                      locked ? (
                        <LockKeyhole size={20} aria-hidden="true" />
                      ) : (
                        <KindIcon kind={activity.kind} />
                      )
                    }
                    title={activity.title}
                    href={
                      openable
                        ? `/activity/${encodeURIComponent(activity.id)}`
                        : undefined
                    }
                    meta={[
                      kindLabel(activity.kind),
                      locked ? lockReason(activity) : null,
                    ]}
                    end={<Badge>{stateLabel(activity.state)}</Badge>}
                  />
                );
              })}
            </List>
          </Panel>
        </div>
      ) : (
        <div className={styles.stack}>
          <header className={styles.courseHeader}>
            <Artwork large />
            <h2>{learning.program_title}</h2>
            <small>Lesson by Dipak Vishwakarma</small>
            <Progress
              value={learning.projection.percentage}
              title={learning.program_title}
            />
          </header>
          {next ? (
            <Link
              className={styles.primaryLink}
              href={`/activity/${encodeURIComponent(next.id)}`}
            >
              Continue: {next.title}
            </Link>
          ) : null}
          <Panel title="Modules">
            {learning.modules.length ? (
              <List label="Course modules">
                {learning.modules.map((item) => {
                  const status = moduleState(item);
                  const done = item.activities.filter(
                    (activity) => activity.state.toLowerCase() === "completed",
                  ).length;
                  return (
                    <Row
                      key={item.id}
                      link={Link}
                      icon={
                        status === "locked" ? (
                          <LockKeyhole size={20} aria-hidden="true" />
                        ) : (
                          <BookOpen size={20} aria-hidden="true" />
                        )
                      }
                      title={item.title}
                      href={
                        status === "locked" || status === "unavailable"
                          ? undefined
                          : `${href}/module/${encodeURIComponent(item.id)}`
                      }
                      meta={[
                        `${done}/${item.activities.length} steps done`,
                        status === "locked"
                          ? "Finish the earlier required steps to unlock."
                          : status === "unavailable"
                            ? "New steps are on the way."
                            : null,
                      ]}
                      end={<Badge>{stateLabel(status)}</Badge>}
                    />
                  );
                })}
              </List>
            ) : (
              <Empty
                link={Link}
                icon={BookOpen}
                title="New lessons are on the way."
                action={{ href: "/learning", label: "My courses" }}
              />
            )}
          </Panel>
        </div>
      )}
    </Screen>
  );
}
