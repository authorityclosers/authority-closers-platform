import { notFound } from "next/navigation";

import { adminRead } from "@/app/lib/server-api";
import {
  DAYS,
  DAY_WORDS,
  daysFrom,
  normalizeTimeline,
} from "@/app/sellers/seller-data";
import { SellerTimeline } from "@/app/sellers/seller-timeline";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Admin → Sellers → What happened (owner, 24 Oct 2026: "finding out what went
 * wrong for a seller is too hard"): one person's days, the workspaces they
 * opened, their devices and versions, what reached the server beside what the
 * phone reported, and a line naming the newest gap.
 */
export default async function SellerPage({
  params,
  searchParams,
}: {
  params: Promise<{ personId: string }>;
  searchParams: Promise<{ days?: string }>;
}) {
  const { personId } = await params;
  if (!UUID.test(personId)) notFound();
  const id = personId.toLowerCase();
  const days = daysFrom((await searchParams).days);
  const result = await adminRead(
    `/v1/admin/sellers/${id}/timeline?days=${days}`,
    normalizeTimeline,
  );
  const back = { href: "/sellers", label: "Sellers" };
  if (!result.ok) {
    return (
      <Page>
        <PageHeader title="What happened" back={back} />
        <Unavailable title="This seller's days" reason={result.error} />
      </Page>
    );
  }
  const timeline = result.data;
  return (
    <Page wide>
      <PageHeader
        title={timeline.person.name ?? timeline.person.email ?? "Seller"}
        back={back}
        context={[
          "What happened",
          timeline.person.email,
          timeline.person.status !== "active" ? timeline.person.status : null,
        ]}
      />
      <QueryTabs
        base={`/sellers/${id}`}
        param="days"
        items={DAYS.map((key) => ({ key, label: DAY_WORDS[key] }))}
        current={days}
      />
      <SellerTimeline timeline={timeline} />
    </Page>
  );
}
