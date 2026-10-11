import { InvitesView } from "./invites-view";

/** The invitation email's link: /organisation/invites?invite_id=<id>. */
export default async function InvitesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // The static preview has no request to read (as on the home page).
  const inviteId =
    process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1"
      ? undefined
      : (await searchParams).invite_id;
  return (
    <InvitesView inviteId={typeof inviteId === "string" ? inviteId : null} />
  );
}
