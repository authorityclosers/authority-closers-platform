import { redirect } from "next/navigation";

/** /billing redirects to Settings → Plan & billing (owner order 3 Oct). */
export default function BillingPage() {
  redirect("/account#billing");
}
