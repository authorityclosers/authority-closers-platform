import { notFound } from "next/navigation";

import { CallMap } from "@/app/calls/call-map";
import { normalizeMap } from "@/app/calls/call-map-data";
import { LiveRefresh } from "@/app/calls/live-refresh";
import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** One call's pipeline map: every stage with status, timing, cost, provider and version. */
export default async function CallMapPage({
  params,
}: {
  params: Promise<{ recordingId: string }>;
}) {
  const { recordingId } = await params;
  if (!UUID.test(recordingId)) notFound();
  const result = await adminRead(
    `/v1/admin/conversation/calls/${recordingId}/data-map`,
    normalizeMap,
  );
  const back = { href: `/calls/${recordingId}`, label: "Call" };
  if (!result.ok)
    return (
      <Page>
        <PageHeader title="Pipeline map" back={back} />
        <Unavailable title="This call's pipeline map" reason={result.error} />
      </Page>
    );
  const map = result.data;
  return (
    <Page>
      <PageHeader
        title="Pipeline map"
        back={back}
        context={[map.workspace, map.state, recordingId.slice(0, 8)]}
      />
      <LiveRefresh
        active={map.stages.some((stage) => stage.status === "running")}
      />
      <CallMap map={map} />
    </Page>
  );
}
