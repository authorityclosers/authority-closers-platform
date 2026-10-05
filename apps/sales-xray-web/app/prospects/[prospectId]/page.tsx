import { notFound } from "next/navigation";

import { UUID_RE } from "../../prospects-client";
import { ProspectDetailView } from "../prospect-detail-view";

// The static preview build needs one concrete path; real prospects render on
// demand and any non-UUID is not found.
export function generateStaticParams() {
  return [{ prospectId: "11111111-1111-4111-8111-111111111111" }];
}

export default async function ProspectDetailPage({
  params,
}: {
  params: Promise<{ prospectId: string }>;
}) {
  const { prospectId } = await params;
  if (!UUID_RE.test(prospectId)) {
    notFound();
  }
  return <ProspectDetailView prospectId={prospectId} />;
}
