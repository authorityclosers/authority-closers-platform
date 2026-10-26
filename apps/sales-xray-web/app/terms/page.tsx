import { PolicyPage } from "../policy-content";
import { publicPolicyMetadata } from "../policy-metadata";

export const metadata = publicPolicyMetadata("terms");

export default function TermsPage() {
  return <PolicyPage slug="terms" />;
}
