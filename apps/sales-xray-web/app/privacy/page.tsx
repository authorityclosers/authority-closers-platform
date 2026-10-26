import { PolicyPage } from "../policy-content";
import { publicPolicyMetadata } from "../policy-metadata";

export const metadata = publicPolicyMetadata("privacy");

export default function PrivacyPage() {
  return <PolicyPage slug="privacy" />;
}
