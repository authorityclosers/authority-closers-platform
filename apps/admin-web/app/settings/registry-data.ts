/**
 * The Admin settings registry (GET /v1/admin/settings, ac.admin-settings/1):
 * each setting, where its value is read and how it is changed through its
 * area's own route. The same steps as the API's reference (registry.py):
 * read the area's answer, take the revision from it, and for an area that
 * takes its whole document back, set the one field in that document. Pure.
 */
import { read } from "../lib/read";

export type SettingKind = "bool" | "int" | "enum" | "money_paise" | "text";

export type RegistrySetting = {
  id: string;
  area: string;
  label: string;
  kind: SettingKind;
  help: string | null;
  read: {
    path: string;
    value: string;
    revision: string | null;
    changedAt: string | null;
  };
  write: {
    method: "POST" | "PUT";
    path: string;
    body: Record<string, unknown>;
    idempotencyKey: boolean;
    merge: { container: string; key: string[] } | null;
    needsReason: boolean;
  } | null;
  minimum: number | null;
  maximum: number | null;
  maximumFrom: string | null;
  options: { value: string; label: string }[];
  optionsFrom: { list: string; value: string; label: string } | null;
  labels: Record<string, string> | null;
  whyNot: string | null;
};

export type Registry = { settings: RegistrySetting[] };

const KINDS: readonly SettingKind[] = [
  "bool",
  "int",
  "enum",
  "money_paise",
  "text",
];

const options = (raw: unknown) =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return {
      value: read.string(row.value),
      label: read.string(row.label, read.string(row.value)),
    };
  });

export function normalizeRegistry(raw: unknown): Registry {
  const body = read.object(raw);
  return {
    settings: read.array(body.settings).map((item) => {
      const row = read.object(item);
      const readAt = read.object(row.read);
      const write = row.write ? read.object(row.write) : null;
      const merge = write?.merge ? read.object(write.merge) : null;
      const from = row.options_from ? read.object(row.options_from) : null;
      const kind = read.string(row.kind);
      const method = write ? read.string(write.method) : "";
      return {
        id: read.string(row.id),
        area: read.string(row.area),
        label: read.string(row.label, read.string(row.id)),
        kind: (KINDS as readonly string[]).includes(kind)
          ? (kind as SettingKind)
          : "text",
        help: read.optionalString(row.help),
        read: {
          path: read.string(readAt.path),
          value: read.string(readAt.value),
          revision: read.optionalString(readAt.revision),
          changedAt: read.optionalString(readAt.changed_at),
        },
        write:
          write && (method === "POST" || method === "PUT")
            ? {
                method,
                path: read.string(write.path),
                body: read.object(write.body),
                idempotencyKey: write.idempotency_key !== false,
                merge: merge
                  ? {
                      container: read.string(merge.container),
                      key: read.strings(merge.key),
                    }
                  : null,
                needsReason: write.needs_reason === true,
              }
            : null,
        minimum: read.optionalNumber(row.minimum),
        maximum: read.optionalNumber(row.maximum),
        maximumFrom: read.optionalString(row.maximum_from),
        options: options(row.options),
        optionsFrom: from
          ? {
              list: read.string(from.list),
              value: read.string(from.value),
              label: read.string(from.label),
            }
          : null,
        labels: row.labels
          ? Object.fromEntries(
              Object.entries(read.object(row.labels)).map(([key, value]) => [
                key,
                read.string(value, key),
              ]),
            )
          : null,
        whyNot: read.optionalString(row.why_not),
      };
    }),
  };
}

/** RFC 6901 JSON pointer; undefined when any step is missing. */
export function pointer(document: unknown, path: string): unknown {
  if (path === "" || path === "/") return document;
  let current: unknown = document;
  for (const raw of path.replace(/^\//, "").split("/")) {
    const part = raw.replaceAll("~1", "/").replaceAll("~0", "~");
    if (Array.isArray(current) && /^\d+$/.test(part))
      current = current[Number(part)];
    else if (current && typeof current === "object" && part in current)
      current = (current as Record<string, unknown>)[part];
    else return undefined;
  }
  return current;
}

/** The value now, as the setting's answer holds it. */
export const currentValue = (setting: RegistrySetting, answer: unknown) =>
  pointer(answer, setting.read.value);

/** Fixed options, or the menu the answer carries (e.g. the call data models). */
export function optionsFor(setting: RegistrySetting, answer: unknown) {
  if (!setting.optionsFrom) return setting.options;
  const { list, value, label } = setting.optionsFrom;
  return read.array(pointer(answer, list)).map((item) => {
    const row = read.object(item);
    return {
      value: read.string(row[value]),
      label: read.string(row[label], read.string(row[value])),
    };
  });
}

/** The highest allowed value: fixed, or read from the answer (the approved budget cap). */
export function maximumFor(
  setting: RegistrySetting,
  answer: unknown,
): number | null {
  if (setting.maximumFrom) {
    const found = pointer(answer, setting.maximumFrom);
    return typeof found === "number" ? found : setting.maximum;
  }
  return setting.maximum;
}

export class ChangeRefused extends Error {}

/** The change's body: the API's reference steps, so all three clients send the same. */
export function requestBody(
  setting: RegistrySetting,
  answer: unknown,
  value: unknown,
  reason?: string,
): Record<string, unknown> {
  const write = setting.write;
  if (!write)
    throw new ChangeRefused(
      setting.whyNot ?? "This setting is changed on its page.",
    );
  if (write.needsReason && !reason?.trim())
    throw new ChangeRefused("Give a reason for this change.");
  let merged: unknown = null;
  if (write.merge) {
    const document = pointer(answer, write.merge.container);
    if (!document || typeof document !== "object" || Array.isArray(document))
      throw new ChangeRefused("The current settings could not be read.");
    merged = structuredClone(document) as Record<string, unknown>;
    let target = merged as Record<string, unknown>;
    for (const part of write.merge.key.slice(0, -1)) {
      if (!target[part] || typeof target[part] !== "object") target[part] = {};
      target = target[part] as Record<string, unknown>;
    }
    target[write.merge.key[write.merge.key.length - 1]] = value;
  }
  const fill: Record<string, unknown> = {
    $value: value,
    $revision: setting.read.revision
      ? (pointer(answer, setting.read.revision) ?? null)
      : null,
    $reason: (reason ?? "").trim(),
    $merged: merged,
  };
  return Object.fromEntries(
    Object.entries(write.body).map(([key, template]) => [
      key,
      typeof template === "string" && template in fill
        ? fill[template]
        : template,
    ]),
  );
}

const money = (paise: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);

/** The value in words: its label, its option's name, rupees, or the number. */
export function displayValue(
  setting: RegistrySetting,
  answer: unknown,
): string {
  const value = currentValue(setting, answer);
  if (value === undefined || value === null) return "—";
  if (setting.kind === "bool")
    return setting.labels?.[String(value)] ?? (value ? "On" : "Off");
  if (setting.kind === "money_paise" && typeof value === "number")
    return money(value);
  if (setting.kind === "enum")
    return (
      optionsFor(setting, answer).find((item) => item.value === value)?.label ??
      String(value)
    );
  if (typeof value === "number") return value.toLocaleString("en-IN");
  return String(value);
}
