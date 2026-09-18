import { AdminShell } from "../components/admin-shell";
import { PeopleDirectory } from "../components/people-directory";

export default function PeoplePage() {
  return (
    <AdminShell
      active="people"
      surface="people"
      eyebrow="Academy / People"
      title="People"
      description="Your learners and team, with course activity and support in one place."
    >
      <PeopleDirectory />
    </AdminShell>
  );
}
