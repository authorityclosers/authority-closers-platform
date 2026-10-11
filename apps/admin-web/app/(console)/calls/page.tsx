import Link from "next/link";
import { Clapperboard } from "lucide-react";

import { CallTable } from "@/app/calls/call-table";
import { normalizeQueue } from "@/app/calls/call-data";
import { REVIEW_LABEL, REVIEW_STATES } from "@/app/calls/labels-data";
import { QueueFilters } from "@/app/calls/queue-filters";
import { QueueKeys } from "@/app/calls/queue-keys";
import {
  filterQuery,
  queueApiPath,
  queueFilters,
} from "@/app/calls/queue-query";
import styles from "@/app/calls/calls.module.css";
import { adminRead } from "@/app/lib/server-api";
import {
  Empty,
  Kbd,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const EMPTY_FACETS = {
  organisations: [],
  reps: [],
  languages: [],
  providers: [],
  prompts: [],
};

export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = queueFilters(await searchParams);
  const queue = await adminRead(queueApiPath(filters), normalizeQueue);
  const data = queue.ok ? queue.data : null;
  const all = data
    ? REVIEW_STATES.reduce((sum, state) => sum + data.reviewCounts[state], 0)
    : undefined;
  const back = filterQuery(filters);
  return (
    <Page wide>
      <QueueKeys />
      <PageHeader
        title="Calls"
        context={[
          "Every analysed call across organisations, newest first",
          data ? `${data.total} shown` : null,
        ]}
        actions={
          <span className={styles.hint}>
            <Kbd>J</Kbd>
            <Kbd>K</Kbd> move · <Kbd>Enter</Kbd> open
          </span>
        }
      />
      <QueueFilters filters={filters} facets={data?.facets ?? EMPTY_FACETS} />
      <QueryTabs
        base="/calls"
        param="review"
        keep={filterQuery(filters, ["review", "cursor"])}
        current={filters.review ?? "all"}
        items={[
          { key: "all", label: "All", count: all },
          ...REVIEW_STATES.map((state) => ({
            key: state,
            label: REVIEW_LABEL[state],
            count: data?.reviewCounts[state],
          })),
        ]}
      />
      {!queue.ok ? (
        <Unavailable title="The call queue" reason={queue.error} />
      ) : null}
      {data ? (
        <Panel
          title="Queue"
          sub={
            data.truncated
              ? `Newest ${data.windowSize} calls; narrow by date to see older ones`
              : undefined
          }
          foot={
            data.nextCursor || filters.cursor ? (
              <span className={styles.pager}>
                <span>
                  {data.items.length} of {data.total}
                </span>
                <span>
                  {filters.cursor ? (
                    <Link
                      href={`/calls?${filterQuery(filters, ["cursor"])}`}
                      className={kitStyles.panelAction}
                    >
                      First page
                    </Link>
                  ) : null}{" "}
                  {data.nextCursor ? (
                    <Link
                      href={`/calls?${filterQuery({ ...filters, cursor: data.nextCursor })}`}
                      className={kitStyles.panelAction}
                    >
                      Next page
                    </Link>
                  ) : null}
                </span>
              </span>
            ) : undefined
          }
        >
          {data.items.length ? (
            <CallTable items={data.items} back={back} />
          ) : (
            <Empty
              icon={Clapperboard}
              title="No calls match"
              text="Change or clear the filters. Calls appear here once they're uploaded."
            />
          )}
        </Panel>
      ) : null}
    </Page>
  );
}
