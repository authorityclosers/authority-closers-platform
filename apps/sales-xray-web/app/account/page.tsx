import { AccountView } from "../account-view";
import { StandaloneStudio } from "../standalone-studio";

/** The signed-in account: identity, contact details and analysis allowance. */
export default function AccountPage() {
  return (
    <StandaloneStudio>
      <AccountView />
    </StandaloneStudio>
  );
}
