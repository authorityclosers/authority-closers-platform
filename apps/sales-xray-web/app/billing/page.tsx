import { redirect } from "next/navigation";

/** /billing redirects to Settings → Plan & usage (owner order 3 Oct; Settings 20 Oct). */
export default function BillingPage() {
  redirect("/settings/plan");
}
