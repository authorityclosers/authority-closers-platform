import { AdminShell } from "../components/admin-shell";
import { PeopleRuntime } from "../components/people-runtime";

export default function PeoplePage() {
  return (
    <AdminShell
      active="people"
      surface="people"
      eyebrow="People / learner support"
      title="People"
      description="Find an active learner and inspect course access, progress and saved-work status in this academy."
    >
      <PeopleRuntime />
    </AdminShell>
  );
}
