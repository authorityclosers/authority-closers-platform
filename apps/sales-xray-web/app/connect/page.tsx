import type { Metadata } from "next";

import { ConnectView } from "./connect-view";

export const metadata: Metadata = {
  title: "Connect an app · Sales X-Ray",
  robots: { index: false, follow: false },
};

/** Connect (OAuth 2.0 + PKCE): the consent screen another app sends people to. */
export default function ConnectPage() {
  return <ConnectView />;
}
