"use client";

import { roleLabel } from "../roles";
import { Building2, MailOpen } from "lucide-react";
import { useRef, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { requestWorkspace } from "../../call-ownership";
import { notify } from "../../notice-center";
import {
  dropInvite,
  refreshInvites,
  useInvites,
} from "../../shell/invites-store";
import { useShellProfile } from "../../shell/profile-store";
import { Button, Empty, List, PageHeader, Panel, Row } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import {
  acceptInvite,
  OrgApiError,
  type PendingInvite,
} from "../organisation-api";
import styles from "./invites.module.css";
import { InvitesSkeleton } from "./invites-skeleton";

const day = (value: string | null) => {
  const time = value ? Date.parse(value) : NaN;
  return Number.isFinite(time)
    ? new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
      }).format(time)
    : null;
};

/**
 * Invitations waiting for the signed-in person. The email links here with
 * its invite; Join accepts it and opens the organisation.
 */
export function InvitesView({ inviteId }: { inviteId: string | null }) {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true;
  const state = useInvites(signedIn);
  const profile = useShellProfile(signedIn);
  const [joining, setJoining] = useState<string | null>(null);
  // Accepted: the shell moves into it; if that move fails, open it from here.
  const [joined, setJoined] = useState<{
    tenantId: string;
    name: string;
  } | null>(null);
  const keys = useRef(new Map<string, string>());

  const join = async (invite: PendingInvite) => {
    if (joining) return;
    setJoining(invite.inviteId);
    const key = keys.current.get(invite.inviteId) ?? crypto.randomUUID();
    keys.current.set(invite.inviteId, key);
    try {
      const accepted = await acceptInvite(invite.inviteId, key);
      dropInvite(invite.inviteId);
      setJoined({
        tenantId: accepted.tenantId,
        name: invite.organisationName,
      });
      requestWorkspace(accepted.tenantId, "/organisation");
    } catch (error) {
      const closed =
        error instanceof OrgApiError && [404, 409].includes(error.status);
      if (closed) refreshInvites();
      notify({
        id: "invite-join",
        tone: "error",
        title: `Couldn’t join ${invite.organisationName}`,
        message:
          error instanceof OrgApiError
            ? error.message
            : "Check your connection and try again.",
        action: closed
          ? undefined
          : { label: "Try again", run: () => void join(invite) },
      });
    }
    setJoining(null);
  };

  const asked = inviteId
    ? (state.invites.find((invite) => invite.inviteId === inviteId) ?? null)
    : null;
  // The one this link is for leads; it alone gets the primary button.
  const invites = asked
    ? [asked, ...state.invites.filter((invite) => invite !== asked)]
    : state.invites;

  let body;
  if (joined)
    body = (
      <Empty
        icon={Building2}
        title={`You joined ${joined.name}`}
        text="Opening it now."
        action={{
          label: `Open ${joined.name}`,
          onClick: () => requestWorkspace(joined.tenantId, "/organisation"),
        }}
      />
    );
  else if (access?.authenticated === false)
    body = (
      <Empty
        icon={MailOpen}
        title="Sign in to answer your invitation"
        text="Use the email address the invitation was sent to."
        action={
          access.requestAccountSignIn
            ? { label: "Sign in", onClick: access.requestAccountSignIn }
            : { label: "Sign in", href: "/login" }
        }
      />
    );
  else if (!signedIn || !state.ready) body = <InvitesSkeleton bare />;
  else if (!state.live)
    body = (
      <Empty
        icon={MailOpen}
        title="Invitations aren’t available here yet"
        text="This server can’t answer invitations yet. Nothing on your account has changed."
        action={{ label: "Go to Dashboard", href: "/" }}
      />
    );
  else
    body = (
      <>
        {inviteId && !asked ? (
          <p className={styles.note} role="status">
            That invitation isn’t open
            {profile?.email ? ` for ${profile.email}` : " for this account"}. It
            may have been used, withdrawn or expired, or sent to another email.
            Ask whoever invited you for a new one.
          </p>
        ) : null}
        {invites.length ? (
          <Panel title="Waiting for you" sub={invites.length}>
            <List label="Invitations">
              {invites.map((invite, index) => {
                const until = day(invite.expiresAt);
                return (
                  <Row
                    key={invite.inviteId}
                    icon={<Building2 size={15} aria-hidden="true" />}
                    title={invite.organisationName}
                    meta={[
                      `Invited as ${roleLabel(invite.role).toLowerCase()}`,
                      until ? `Open until ${until}` : null,
                    ]}
                    end={
                      <Button
                        variant={index === 0 ? "primary" : "secondary"}
                        disabled={joining !== null}
                        aria-label={`Join ${invite.organisationName}`}
                        onClick={() => void join(invite)}
                      >
                        {joining === invite.inviteId ? "Joining…" : "Join"}
                      </Button>
                    }
                  />
                );
              })}
            </List>
          </Panel>
        ) : (
          <Empty
            icon={MailOpen}
            title="No invitations waiting"
            text={
              profile?.email
                ? `Invitations sent to ${profile.email} appear here.`
                : "Invitations sent to your email appear here."
            }
            action={{ label: "Go to Dashboard", href: "/" }}
          />
        )}
      </>
    );

  return (
    <AcquisitionShell
      authenticated={signedIn}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.page}>
        <PageHeader title="Invitations" />
        {body}
      </div>
    </AcquisitionShell>
  );
}

export { InvitesSkeleton };
