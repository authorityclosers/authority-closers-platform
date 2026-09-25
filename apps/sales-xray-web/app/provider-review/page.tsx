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
  if ((await headers()).get("host")?.toLowerCase() !== STAGING_HOST) notFound();

  const { call } = await searchParams;
  if (typeof call !== "string" || !UUID.test(call)) notFound();

  return <ProviderReview submissionId={call} />;
}
