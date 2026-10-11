import { AdminShell } from "@/app/components/admin-shell";
import { MinuteAccountAdminPanel } from "@/app/sales-xray/minute-account-admin";

export const dynamic = "force-dynamic";

export default function MinutesPage() {
  return (
    <AdminShell
      active="sales-xray"
      title="Minutes"
      description="Find an account by exact email or username and grant analysis minutes. Every grant needs a reason."
    >
      <MinuteAccountAdminPanel />
    </AdminShell>
  );
}
