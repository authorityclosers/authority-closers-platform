import { redirect } from "next/navigation";

import { adminRead } from "@/app/lib/server-api";
import { normalizeFound, sellerPath } from "@/app/sellers/seller-data";
import styles from "@/app/sellers/sellers.module.css";
import { Button, Field, Page, PageHeader, Panel } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Sellers (owner, 24 Oct 2026): find one seller by the email they signed
 * up with, then read what happened day by day. Organisations' member rows and
 * bug reports open the same page.
 */
export default async function SellersPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string }>;
}) {
  const email = ((await searchParams).email ?? "").trim();
  let problem: string | null = null;
  if (email) {
    const result = await adminRead(
      `/v1/admin/sellers?email=${encodeURIComponent(email)}`,
      normalizeFound,
    );
    if (result.ok && result.data) redirect(sellerPath(result.data.id));
    problem =
      result.ok || result.status === 404
        ? "No one has signed up with that email."
        : result.error;
  }
  return (
    <Page>
      <PageHeader
        title="Sellers"
        context={["What happened for one seller, day by day"]}
      />
      <Panel
        title="Find a seller"
        sub="The email they signed up with. Member rows in Organisations and bug reports open the same page."
      >
        <form method="get" action="/sellers" className={styles.find}>
          <Field label="Email" error={problem}>
            <input
              type="email"
              name="email"
              defaultValue={email}
              required
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Button type="submit" variant="primary">
            Open their days
          </Button>
        </form>
      </Panel>
    </Page>
  );
}
