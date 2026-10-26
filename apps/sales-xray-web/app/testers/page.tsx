import type { Metadata } from "next";

import { TestersPage } from "./testers-page";

export const metadata: Metadata = {
  title: "Test Sales X-Ray",
  description: "Help us test Sales X-Ray: three steps, five minutes.",
};

export default function Page() {
  return <TestersPage />;
}
