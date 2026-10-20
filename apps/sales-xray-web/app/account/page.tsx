import { AccountRedirect } from "../settings/account-redirect";

/** The account now lives in Settings: /account#<section> opens that section there. */
export default function AccountPage() {
  return <AccountRedirect />;
}
