import { redirect } from "next/navigation";

/** /account/billing redirects to Settings → Plan & billing (/account#billing). */
export default function AccountBillingPage() {
  redirect("/account#billing");
}
