import type { Metadata } from "next";

import { AppsView } from "./apps-view";
import { latestAndroidRelease } from "./release";

export const metadata: Metadata = {
  title: "Get the Sales Xray apps · Authority Closers",
  description: "Download Sales Xray for Android, with install help.",
};

// Public, signed out too. The release details are re-read at most every 10 minutes.
export const revalidate = 600;

export default async function AppsPage() {
  return <AppsView android={await latestAndroidRelease()} />;
}
