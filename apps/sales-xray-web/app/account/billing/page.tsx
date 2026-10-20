import { redirect } from "next/navigation";

/** /account/billing redirects to Settings → Plan & usage (/settings/plan). */
export default function AccountBillingPage() {
  redirect("/settings/plan");
}
