import { Building2, ShieldCheck } from "lucide-react";

import { loadConsoleAccess } from "@/app/lib/console-access";
import { adminRead } from "@/app/lib/server-api";
import { BillingPanel } from "@/app/platform/billing-panel";
import {
  PLATFORM_PERMISSION_NAMES,
  isUuid,
  normalizeAcademies,
} from "@/app/platform/platform-data";
import {
  Badge,
  Empty,
  List,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Row,
  Unavailable,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

export default async function PlatformPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; after?: string }>;
}) {
  const { tab, after } = await searchParams;
  const access = await loadConsoleAccess();
  const canRead = access.platform.includes("platform_tenants_read");
  const canBill = access.platform.includes("platform_billing_manage");
  const tabs = [
    ...(canRead ? [{ key: "academies", label: "Academies" }] : []),
    ...(canBill ? [{ key: "billing", label: "Billing" }] : []),
    { key: "access", label: "Your access" },
  ];
  const current = tabs.find((item) => item.key === tab)?.key ?? tabs[0]!.key;
  const academies =
    current === "academies"
      ? await adminRead(
          `/v1/platform/tenants${isUuid(after) ? `?after_id=${after}` : ""}`,
          normalizeAcademies,
        )
      : null;
  return (
    <Page>
      <PageHeader
        title={current === "billing" ? "Billing" : "Platform"}
        context={["Every academy and team on the platform, kept apart"]}
      />
      <QueryTabs base="/platform" items={tabs} current={current} />
      {current === "billing" ? <BillingPanel /> : null}
      {current === "academies" && academies && !academies.ok ? (
        <Unavailable title="Academies" reason={academies.error} />
      ) : null}
      {current === "academies" && academies?.ok ? (
        <Panel
          title="Academies"
          sub={`${academies.data.academies.length} shown`}
          action={
            academies.data.nextAfterId
              ? {
                  href: `/platform?after=${academies.data.nextAfterId}`,
                  label: "Next academies",
                }
              : isUuid(after)
                ? { href: "/platform", label: "Back to the first page" }
                : undefined
          }
        >
          {academies.data.academies.length === 0 ? (
            <Empty icon={Building2} title="No academies yet" />
          ) : (
            <List label="Academies">
              {academies.data.academies.map((academy) => (
                <Row
                  key={academy.id}
                  icon={<Building2 size={16} aria-hidden="true" />}
                  title={academy.name}
                  meta={[
                    academy.kind === "platform"
                      ? "Platform operations"
                      : "Academy workspace",
                  ]}
                  end={
                    <Badge
                      tone={
                        academy.status === "active"
                          ? "good"
                          : academy.status === "suspended"
                            ? "warn"
                            : "neutral"
                      }
                    >
                      {academy.status}
                    </Badge>
                  }
                />
              ))}
            </List>
          )}
        </Panel>
      ) : null}
      {current === "access" ? (
        <Panel title="Your platform access" sub={access.email ?? undefined}>
          {access.platform.length === 0 ? (
            <Empty
              icon={ShieldCheck}
              title="No platform permissions"
              text="Platform work needs a named grant. Academy admin rights don't carry over."
            />
          ) : (
            <List label="Platform permissions">
              {access.platform.map((permission) => (
                <Row
                  key={permission}
                  icon={<ShieldCheck size={16} aria-hidden="true" />}
                  title={PLATFORM_PERMISSION_NAMES[permission] ?? permission}
                  meta={[permission]}
                />
              ))}
            </List>
          )}
        </Panel>
      ) : null}
    </Page>
  );
}
