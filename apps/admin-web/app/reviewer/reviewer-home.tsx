"use client";

import { Inbox, LogIn } from "lucide-react";
import { useEffect, useState } from "react";

import { istStamp } from "../lib/time";
import {
  Badge,
  Button,
  Empty,
  List,
  Page,
  PageHeader,
  Panel,
  Row,
  Skeleton,
  Unavailable,
  kitStyles,
} from "../ui/kit";

import {
  createReviewerAssignmentApi,
  reviewerErrorMessage,
  ReviewerApiProblem,
  type ReviewerAssignmentSummary,
} from "./reviewer-api";
import { useReviewerSession } from "./reviewer-session";
import styles from "./reviewer-home.module.css";

type State = ReviewerAssignmentSummary["state"];
const STATE_TONE: Record<State, "accent" | "warn" | "good" | "neutral"> = {
  assigned: "accent",
  in_progress: "warn",
  submitted: "good",
  revoked: "neutral",
  expired: "neutral",
};
const LENS: Record<
  ReviewerAssignmentSummary["allowed_lenses"][number],
  string
> = {
  sales: "Sales expert",
  technical: "Developer",
  ux: "Experience reviewer",
};

function stateLabel(value: State) {
  return value === "in_progress"
    ? "In progress"
    : value.charAt(0).toUpperCase() + value.slice(1);
}

export function ReviewerHome() {
  const { status, session, refresh } = useReviewerSession();
  const [items, setItems] = useState<ReviewerAssignmentSummary[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [queueState, setQueueState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");

  useEffect(() => {
    if (status !== "ready") return;
    const controller = new AbortController();
    void createReviewerAssignmentApi()
      .queue(controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setItems(payload.items);
        setTruncated(payload.truncated);
        setQueueState("ready");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (
          reason instanceof ReviewerApiProblem &&
          (reason.status === 401 || reason.status === 403)
        )
          void refresh();
        setError(reviewerErrorMessage(reason));
        setQueueState("error");
      });
    return () => controller.abort();
  }, [refresh, status]);

  return (
    <main id="admin-content" className={styles.main} tabIndex={-1}>
      <Page>
        <PageHeader
          title="Your review assignments"
          context={[
            session ? session.display_name || session.email : null,
            "Each assignment has its own call, transcript and feedback lenses",
          ]}
        />
        {status === "loading" ||
        (status === "ready" && queueState === "loading") ? (
          <Panel title="Assignments">
            <div className={styles.loading}>
              <p role="status" className={kitStyles.srOnly}>
                {status === "loading"
                  ? "Checking your reviewer session…"
                  : "Loading your assignments…"}
              </p>
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} height={36} />
              ))}
            </div>
          </Panel>
        ) : null}
        {status === "signed_out" ? (
          <Panel title="Assignments">
            <Empty
              icon={LogIn}
              title="Sign in to see assignments"
              text="Use the one-time link sent to your reviewer email."
              action={{ href: "/reviewer/login", label: "Sign in to review" }}
            />
          </Panel>
        ) : null}
        {status === "error" ? (
          <div className={styles.retry}>
            <Unavailable
              title="Your reviewer session"
              reason="The workspace could not verify your dedicated session. Refresh to try again."
            />
            <Button onClick={() => window.location.reload()}>
              Refresh workspace
            </Button>
          </div>
        ) : null}
        {status === "ready" && queueState === "error" ? (
          <div className={styles.retry}>
            <Unavailable title="Your assignment list" reason={error} />
            <Button onClick={() => window.location.reload()}>
              Retry assignments
            </Button>
          </div>
        ) : null}
        {status === "ready" && queueState === "ready" ? (
          <Panel
            title="Assignments"
            sub={`${items.length}${truncated ? "+" : ""}`}
            foot={truncated ? "Showing the first 50 assignments." : undefined}
          >
            {items.length === 0 ? (
              <Empty
                icon={Inbox}
                title="No assignments right now"
                text="There are no active reviewer assignments for this session."
              />
            ) : (
              <List label="Assignments">
                {items.map((item) => (
                  <Row
                    key={item.id}
                    href={`/reviewer/review/${encodeURIComponent(item.id)}`}
                    title="Conversation review"
                    meta={[
                      item.allowed_lenses.map((lens) => LENS[lens]).join(" · "),
                      `Open until ${istStamp(new Date(item.expires_at_epoch * 1000))}`,
                      `Run ${item.run_id.slice(0, 8)}…`,
                    ]}
                    end={
                      <Badge tone={STATE_TONE[item.state]}>
                        {stateLabel(item.state)}
                      </Badge>
                    }
                  />
                ))}
              </List>
            )}
          </Panel>
        ) : null}
      </Page>
    </main>
  );
}
