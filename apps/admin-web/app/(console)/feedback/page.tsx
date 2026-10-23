import Link from "next/link";
import { MessageSquareHeart } from "lucide-react";

import { when } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import {
  MOMENTS,
  MOMENT_LABEL,
  feedbackApiPath,
  feedbackFilters,
  feedbackQuery,
  goodShare,
  normalizeFeedback,
  worse,
} from "@/app/feedback/feedback-data";
import styles from "@/app/feedback/feedback.module.css";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Table,
  Unavailable,
  Why,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const RATING = {
  good: { label: "Great", tone: "good" },
  okay: { label: "Okay", tone: "warn" },
  bad: { label: "Not good", tone: "bad" },
} as const;

function share(value: number | null) {
  return value === null ? "–" : `${value}%`;
}

/** What people say about Sales X-Ray after key moments and updates (owner, 23 Oct 2026). */
export default async function FeedbackPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = feedbackFilters(await searchParams);
  const result = await adminRead(feedbackApiPath(filters), normalizeFeedback);
  const data = result.ok ? result.data : null;
  const keep = feedbackQuery(filters, ["days"]);
  const totals = data?.moments.reduce(
    (sum, row) => ({
      good: sum.good + row.good,
      okay: sum.okay + row.okay,
      bad: sum.bad + row.bad,
      dismissed: sum.dismissed + row.dismissed,
      optedOut: sum.optedOut + row.optedOut,
      comments: sum.comments + row.comments,
    }),
    { good: 0, okay: 0, bad: 0, dismissed: 0, optedOut: 0, comments: 0 },
  );
  return (
    <Page wide>
      <PageHeader
        title="Feedback"
        context={[
          filters.moment ? MOMENT_LABEL[filters.moment] : "Every moment",
          totals ? `${share(goodShare(totals))} say Great` : null,
        ]}
        actions={
          <Why detail="After a key moment (reading a Report, logging a call, the first import, buying a plan, using Chats, an update) Sales X-Ray may ask one quick question: at most once a day and three times a week per person, never during a call or with a sheet open. A Not good with words also becomes a bug report, so it reaches Bugs and the work board." />
        }
      />
      <QueryTabs
        base="/feedback"
        param="days"
        keep={keep || undefined}
        current={String(filters.days)}
        items={[
          { key: "30", label: "30 days" },
          { key: "7", label: "7 days" },
          { key: "90", label: "90 days" },
        ]}
      />
      <nav className={styles.moments} aria-label="Moments">
        <Link
          href={`/feedback?${feedbackQuery({ days: filters.days })}`}
          className={styles.moment}
          aria-current={!filters.moment ? "page" : undefined}
        >
          Every moment
        </Link>
        {MOMENTS.map((moment) => (
          <Link
            key={moment}
            href={`/feedback?${feedbackQuery({ days: filters.days, moment })}`}
            className={styles.moment}
            aria-current={filters.moment === moment ? "page" : undefined}
          >
            {MOMENT_LABEL[moment]}
          </Link>
        ))}
      </nav>
      {!result.ok ? (
        <Unavailable title="Feedback" reason={result.error} />
      ) : !data ||
        !totals ||
        totals.good + totals.okay + totals.bad + totals.dismissed === 0 ? (
        <Panel title="Answers">
          <Empty
            icon={MessageSquareHeart}
            title="No answers yet"
            text="Answers appear here as people use Sales X-Ray. Each one is short: a face, sometimes a few words."
          />
        </Panel>
      ) : (
        <>
          {worse(data.week) ? (
            <section className={styles.alert} role="status">
              <Badge tone="bad">More Not good this week</Badge>
              <span>
                {data.week.bad} of {data.week.rated} answers this week were Not
                good, against {data.week.badBefore} of {data.week.ratedBefore}{" "}
                the week before. Read the comments below; those with words are
                in Bugs.
              </span>
            </section>
          ) : null}
          <Panel title="By moment" sub={`Last ${data.days} days`}>
            <Table label="Feedback by moment">
              <thead>
                <tr>
                  <th scope="col">Moment</th>
                  <th scope="col">Great</th>
                  <th scope="col">Okay</th>
                  <th scope="col">Not good</th>
                  <th scope="col">Say Great</th>
                  <th scope="col">Not now</th>
                  <th scope="col">Don&apos;t ask</th>
                  <th scope="col">With words</th>
                </tr>
              </thead>
              <tbody>
                {data.moments.map((row) => (
                  <tr key={row.moment}>
                    <th scope="row">
                      {MOMENT_LABEL[row.moment] ?? row.moment}
                    </th>
                    <td className={styles.number}>{row.good}</td>
                    <td className={styles.number}>{row.okay}</td>
                    <td className={styles.number}>{row.bad}</td>
                    <td className={styles.number}>{share(goodShare(row))}</td>
                    <td className={styles.number}>{row.dismissed}</td>
                    <td className={styles.number}>{row.optedOut}</td>
                    <td className={styles.number}>{row.comments}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          <div className={styles.columns}>
            <Panel title="By release" sub="Newest first">
              <Table label="Feedback by release">
                <thead>
                  <tr>
                    <th scope="col">Release</th>
                    <th scope="col">Great</th>
                    <th scope="col">Okay</th>
                    <th scope="col">Not good</th>
                    <th scope="col">Say Great</th>
                  </tr>
                </thead>
                <tbody>
                  {data.releases.map((row) => (
                    <tr key={row.release}>
                      <th scope="row" className={styles.mono}>
                        {row.release.slice(0, 12)}
                      </th>
                      <td className={styles.number}>{row.good}</td>
                      <td className={styles.number}>{row.okay}</td>
                      <td className={styles.number}>{row.bad}</td>
                      <td className={styles.number}>{share(goodShare(row))}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
            <Panel title="By day">
              <ol className={styles.days}>
                {data.byDay.map((row) => {
                  const rated = row.good + row.okay + row.bad;
                  return (
                    <li key={row.day}>
                      <span className={styles.day}>{row.day.slice(5)}</span>
                      <span
                        className={styles.bar}
                        aria-label={`${row.good} Great, ${row.okay} Okay, ${row.bad} Not good`}
                      >
                        {rated ? (
                          <>
                            <span
                              data-rating="good"
                              style={{ flexGrow: row.good }}
                            />
                            <span
                              data-rating="okay"
                              style={{ flexGrow: row.okay }}
                            />
                            <span
                              data-rating="bad"
                              style={{ flexGrow: row.bad }}
                            />
                          </>
                        ) : null}
                      </span>
                      <span className={styles.number}>{rated}</span>
                    </li>
                  );
                })}
              </ol>
            </Panel>
          </div>
          <Panel title="What people said" sub="Comments first, newest first">
            <ul className={styles.recent}>
              {data.recent.map((row) => (
                <li key={row.id}>
                  <span className={styles.recentHead}>
                    {row.rating ? (
                      <Badge tone={RATING[row.rating].tone}>
                        {RATING[row.rating].label}
                      </Badge>
                    ) : null}
                    <span>{MOMENT_LABEL[row.moment] ?? row.moment}</span>
                    <small className={kitStyles.muted}>
                      {[row.organisation, row.person, when(row.createdAt)]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </span>
                  {row.comment ? (
                    <p className={styles.comment}>{row.comment}</p>
                  ) : null}
                  <small className={styles.mono}>{row.route}</small>
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
    </Page>
  );
}
