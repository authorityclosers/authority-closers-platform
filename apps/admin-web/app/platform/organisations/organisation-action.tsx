"use client";

import { useEffect, useRef, useState } from "react";
import { AdminApiProblem } from "@ac/operations-web/api";
import {
  loadPlatformIdentity,
  type PlatformIdentity,
} from "@ac/operations-web/platform-identity";
import {
  changePlatformOrganisation,
  type OrganisationCommand,
  type OrganisationMember,
} from "@ac/operations-web/organisations";
import styles from "./organisations.module.css";

export const actionLabels = {
  add: "Add by email",
  role: "Change role",
  remove: "Remove member",
  transfer: "Transfer ownership",
  revoke: "Revoke invite",
};
export type MemberAction = {
  kind: OrganisationCommand["kind"];
  member?: OrganisationMember;
};

export function organisationError(error: unknown) {
  return error instanceof AdminApiProblem
    ? error.message
    : "The request could not be verified. Reload and try again.";
}

export function OrganisationAction({
  action,
  organisation,
  identity,
  onCancel,
  onSuccess,
  onBusy,
  onAccessChanged,
}: {
  action: MemberAction;
  organisation: { tenant_id: string; name: string };
  identity: PlatformIdentity;
  onCancel: () => void;
  onSuccess: () => void;
  onBusy: (busy: boolean) => void;
  onAccessChanged: () => void;
}) {
  const [reason, setReason] = useState("");
  const [role, setRole] = useState<"admin" | "member">(
    action.kind === "add" || action.member?.role === "admin"
      ? "member"
      : "admin",
  );
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const flight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function submit() {
    if (flight.current || reason.trim().length < 3) return;
    flight.current = true;
    setPending(true);
    onBusy(true);
    setError("");
    const current = new AbortController();
    controller.current = current;
    try {
      const fresh = await loadPlatformIdentity({ signal: current.signal });
      if (current.signal.aborted) return;
      if (
        !fresh ||
        fresh.personId !== identity.personId ||
        fresh.sessionId !== identity.sessionId ||
        fresh.selectedTenantId !== identity.selectedTenantId ||
        !fresh.permissions.includes("platform_tenants_read") ||
        !fresh.permissions.includes("platform_organisations_manage")
      ) {
        onAccessChanged();
        return;
      }
      let command: OrganisationCommand;
      if (action.kind === "add") command = { kind: "add", email, role, reason };
      else if (action.kind === "revoke")
        command = {
          kind: "revoke",
          invite_id: action.member!.invite_id!,
          reason,
        };
      else if (action.kind === "role")
        command = {
          kind: "role",
          person_id: action.member!.person_id!,
          role,
          reason,
        };
      else
        command = {
          kind: action.kind,
          person_id: action.member!.person_id!,
          reason,
        };
      await changePlatformOrganisation(organisation.tenant_id, command, {
        signal: current.signal,
      });
      if (!current.signal.aborted) onSuccess();
    } catch (failure) {
      if (!current.signal.aborted) setError(organisationError(failure));
    } finally {
      if (!current.signal.aborted) {
        flight.current = false;
        setPending(false);
        onBusy(false);
      }
    }
  }

  return (
    <section
      className={styles.confirmation}
      aria-labelledby="confirmation-heading"
    >
      <h3 id="confirmation-heading">
        Confirm {actionLabels[action.kind].toLowerCase()}
      </h3>
      <p>
        {organisation.name}
        {action.member &&
          ` · ${action.member.name ?? action.member.email ?? "Unnamed member"}`}
      </p>
      {action.kind === "transfer" && (
        <p>
          The selected member becomes owner. The current owner becomes admin.
        </p>
      )}
      {action.kind === "remove" && (
        <p>This removes the member’s organisation access.</p>
      )}
      {action.kind === "revoke" && (
        <p>This invitation can no longer be accepted.</p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (event.currentTarget.checkValidity()) void submit();
        }}
      >
        <fieldset disabled={pending}>
          {action.kind === "add" && (
            <label>
              Email
              <input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
          )}
          {(action.kind === "add" || action.kind === "role") && (
            <label>
              Role
              <select
                value={role}
                onChange={(event) =>
                  setRole(event.target.value as "admin" | "member")
                }
              >
                <option value="admin">Admin</option>
                <option value="member">Member</option>
              </select>
            </label>
          )}
          <label>
            Reason
            <textarea
              required
              minLength={3}
              maxLength={200}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <p>The reason is recorded with this change.</p>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={reason.trim().length < 3}>
            {pending
              ? "Saving…"
              : `Confirm ${actionLabels[action.kind].toLowerCase()}`}
          </button>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </fieldset>
      </form>
    </section>
  );
}
