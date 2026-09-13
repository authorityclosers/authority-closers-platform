import { LearnerShell } from "../../../components/site-shell";
import { ReviewInvitationAcceptance } from "../review-invitation-acceptance";

export default function ReviewInvitationPage() {
  return (
    <LearnerShell current="sales-xray">
      <ReviewInvitationAcceptance />
    </LearnerShell>
  );
}
