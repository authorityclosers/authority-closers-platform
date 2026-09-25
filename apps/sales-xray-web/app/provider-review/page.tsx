import { headers } from "next/headers";
import { notFound } from "next/navigation";

import { ProviderReview } from "./provider-review";

const STAGING_HOST = "salesxray-staging.authorityclosers.com";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

type PageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

/** This owner action exists only on the exact Sales Xray staging host. */
export default async function Page({ searchParams }: PageProps) {
  // The offline preview has no authenticated request or staging host. Exclude
  // this action before reading dynamic request APIs during static export.
  if (process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1") notFound();
  if ((await headers()).get("host")?.toLowerCase() !== STAGING_HOST) notFound();

  const { call } = await searchParams;
  if (typeof call !== "string" || !UUID.test(call)) notFound();

  return <ProviderReview submissionId={call} />;
}
