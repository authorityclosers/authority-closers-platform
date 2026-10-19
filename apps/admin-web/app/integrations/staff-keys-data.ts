/**
 * Staff keys for the Admin command line and MCP (GET /v1/admin/staff-keys):
 * this person's keys by prefix, with scopes, last use and expiry; never the
 * keys. A new key's answer carries the key once. Pure.
 */
import { read } from "../lib/read";

export type StaffKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  state: "active" | "expired" | "revoked";
  createdAt: string | null;
  expiresAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

export type StaffKeys = {
  keys: StaffKey[];
  limits: {
    active: number;
    days: number;
    freshMinutes: number;
    scopes: string[];
  };
};

export function normalizeStaffKey(raw: unknown): StaffKey {
  const row = read.object(raw);
  const state = read.string(row.state, "active");
  return {
    id: read.string(row.id),
    name: read.string(row.name, "Key"),
    prefix: read.string(row.prefix),
    scopes: read.strings(row.scopes),
    state: state === "expired" || state === "revoked" ? state : "active",
    createdAt: read.optionalString(row.created_at),
    expiresAt: read.optionalString(row.expires_at),
    lastUsedAt: read.optionalString(row.last_used_at),
    revokedAt: read.optionalString(row.revoked_at),
  };
}

export function normalizeStaffKeys(raw: unknown): StaffKeys {
  const body = read.object(raw);
  const limits = read.object(body.limits);
  return {
    keys: read.array(body.keys).map(normalizeStaffKey),
    limits: {
      active: read.number(limits.active, 2),
      days: read.number(limits.days, 30),
      freshMinutes: read.number(limits.fresh_minutes, 10),
      scopes: read.strings(limits.scopes),
    },
  };
}

export const activeKeys = (data: StaffKeys) =>
  data.keys.filter((key) => key.state === "active").length;
