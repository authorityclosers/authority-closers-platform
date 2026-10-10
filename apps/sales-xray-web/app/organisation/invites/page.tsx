import { InvitesView } from "./invites-view";

/** The invitation email's link: /organisation/invites?invite_id=<id>. */
export default async function InvitesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { invite_id: inviteId } = await searchParams;
  return (
    <InvitesView inviteId={typeof inviteId === "string" ? inviteId : null} />
  );
}
