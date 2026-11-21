"use client";

/**
 * Who a setting is for (owner's round-2 board 7, option A, 20 Nov 2026): every
 * item says "Everyone in <organisation>", "Just me" or "This phone", and so does
 * the toast when it is saved.
 */
import { Tag, type Hue } from "../ds";
import "../ds/scale.css";
import { useWorkspaceAccess } from "../workspace-access";

export type SettingScope = "everyone" | "me" | "phone";

const HUE: Record<SettingScope, Hue> = {
  everyone: "green",
  me: "slate",
  phone: "sky",
};

/** The open workspace's name, when it is an organisation. */
export function useOrgName(): string | null {
  const access = useWorkspaceAccess();
  const here = access?.workspaces?.find(
    (workspace) => workspace.tenant_id === access.context?.tenantId,
  );
  return here?.kind === "organisation" ? here.name : null;
}

/** The words: "Everyone in AC Sales Sandbox", "Just me", "This phone". */
export function scopeWords(scope: SettingScope, org: string | null): string {
  if (scope === "phone") return "This phone";
  if (scope === "me") return "Just me";
  return org ? `Everyone in ${org}` : "Everyone";
}

/** The toast's title once saved: "Saved for everyone in AC Sales Sandbox". */
export function savedFor(scope: SettingScope, org: string | null): string {
  if (scope === "phone") return "Saved on this phone";
  if (scope === "me") return "Saved for you";
  return org ? `Saved for everyone in ${org}` : "Saved for everyone";
}

export function ScopeChip({
  scope,
  org,
  short = false,
}: {
  scope: SettingScope;
  /** The organisation's name; read from the workspace when left out. */
  org?: string | null;
  /**
   * The tiny chip beside a section's title (sx-redesign, 21 Nov 2026):
   * "Everyone", "Just me", "This phone"; the full words stay for readers.
   */
  short?: boolean;
}) {
  const here = useOrgName();
  const words = scopeWords(scope, org === undefined ? here : org);
  return (
    // Its own design-system scope: the chip sits in pages that have none.
    <span
      data-pulse-scope=""
      data-scope={scope}
      title={short ? words : undefined}
    >
      <Tag hue={HUE[scope]}>{short ? scopeWords(scope, null) : words}</Tag>
    </span>
  );
}
