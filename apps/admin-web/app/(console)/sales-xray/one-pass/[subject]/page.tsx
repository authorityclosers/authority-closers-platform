import Link from "next/link";

import { adminRead } from "@/app/lib/server-api";
import { CompareDetail } from "@/app/sales-xray/one-pass-compare";
import { normalizeCompared } from "@/app/sales-xray/one-pass-data";
import { Page, PageHeader, Unavailable, kitStyles } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const SUBJECT = /^([0-9a-f-]{36}|[a-z]{2}-[0-9]{2})$/;

/**
 * One call read both ways: today's pipeline and the Google-only one pass, with
 * cost, tokens and time per stage, facts, the 27 pointers, the eight
 * dimensions, the coaching points and which contracts passed. A real call's
 * content read here is audited.
 */
export default async function OnePassCallPage({
  params,
}: {
  params: Promise<{ subject: string }>;
}) {
  const subject = String((await params).subject ?? "");
  const valid = SUBJECT.test(subject);
  const result = valid
    ? await adminRead(
        `/v1/admin/analysis-pipeline/compare/${encodeURIComponent(subject)}`,
        normalizeCompared,
      )
    : null;
  const title =
    result?.ok && result.data.kind === "bench"
      ? `Fictional call ${subject}`
      : `Call ${subject.slice(0, 8)}`;
  return (
    <Page wide>
      <PageHeader
        title={title}
        context={[
          "Today's pipeline beside the one-pass trial · list-price estimates",
        ]}
        actions={
          <span>
            <Link
              href="/sales-xray/one-pass"
              className={kitStyles.button}
              data-variant="ghost"
            >
              All compared calls
            </Link>
            {result?.ok && result.data.kind === "call" ? (
              <Link
                href={`/calls/${subject}/map`}
                className={kitStyles.button}
                data-variant="ghost"
              >
                Call map
              </Link>
            ) : null}
          </span>
        }
      />
      {result?.ok ? (
        <CompareDetail data={result.data} />
      ) : (
        <Unavailable
          title="This comparison"
          reason={result ? result.error : "This is not a call id."}
        />
      )}
    </Page>
  );
}
