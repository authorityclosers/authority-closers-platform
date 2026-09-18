import { AdminShell } from "./components/admin-shell";
import { AdminDashboard } from "./components/admin-dashboard";

export default function AdminHome() {
  return (
    <AdminShell
      active="overview"
      surface="organization"
      eyebrow="Your academy"
      title="Overview"
      description="People, courses and call reviews. Everything you need to keep the academy moving."
      footerText="Academy administration"
    >
      <AdminDashboard />
    </AdminShell>
  );
}
