import type { Metadata } from "next";

import { TestersPage } from "./testers-page";

export const metadata: Metadata = {
  title: "Test Sales X-Ray",
  description:
    "Join the Sales X-Ray early-access group for Android and help shape the app.",
};

export default function Page() {
  return <TestersPage />;
}
