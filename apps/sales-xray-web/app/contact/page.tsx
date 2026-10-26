import { PolicyPage } from "../policy-content";
import { publicPolicyMetadata } from "../policy-metadata";

export const metadata = publicPolicyMetadata("contact");

export default function ContactPage() {
  return <PolicyPage slug="contact" />;
}
