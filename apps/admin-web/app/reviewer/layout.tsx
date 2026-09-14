import { ReviewerSessionProvider } from "./reviewer-session";
import { ReviewerShell } from "./reviewer-session";

export const dynamic = "force-dynamic";

export default function ReviewerLayout({ children }: { children: React.ReactNode }) {
  return <ReviewerSessionProvider><ReviewerShell>{children}</ReviewerShell></ReviewerSessionProvider>;
}
