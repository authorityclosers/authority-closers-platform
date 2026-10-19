"use client";

/**
 * Which environment this Admin is, and one click to the same page in the
 * others. Each environment keeps its own Admin and sign-in today; Usage & cost
 * already reads all three from here. When the Admin API carries the
 * environment on every command (Phase 6), this becomes a scope, not a jump.
 */
import { Check, ChevronDown, ExternalLink } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import styles from "./shell.module.css";
import { usePopover } from "./use-popover";

export type Environment = "development" | "staging" | "production";

export const ENVIRONMENTS: readonly {
  key: Environment;
  label: string;
  host: string;
  hint: string;
}[] = [
  {
    key: "production",
    label: "Production",
    host: "admin.authorityclosers.com",
    hint: "Real customers and the real database",
  },
  {
    key: "staging",
    label: "Staging",
    host: "admin-staging.authorityclosers.com",
    hint: "Each release is checked here before production",
  },
  {
    key: "development",
    label: "Development",
    host: "admin-dev.authorityclosers.com",
    hint: "Live building and testing; sandbox and copied data",
  },
];

export function isEnvironment(value: string | null): value is Environment {
  return ENVIRONMENTS.some((item) => item.key === value);
}

/** The same page in another environment's Admin, query kept. */
export function environmentHref(
  host: string,
  pathname: string,
  search: string,
) {
  return `https://${host}${pathname}${search ? `?${search}` : ""}`;
}

export function EnvironmentSwitch({
  environment,
}: {
  environment: Environment;
}) {
  const pathname = usePathname() ?? "/";
  const search = useSearchParams()?.toString() ?? "";
  const { open, toggle, close, panelId, box, trigger } = usePopover();
  const current = ENVIRONMENTS.find((item) => item.key === environment)!;

  return (
    <span className={styles.envSwitch} ref={box}>
      <button
        type="button"
        ref={trigger}
        className={styles.env}
        data-env={environment}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Environment: ${current.label}. Switch environment`}
        onClick={toggle}
      >
        {current.label}
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      <div
        id={panelId}
        className={styles.envPanel}
        hidden={!open}
        role="region"
        aria-label="Environments"
      >
        <p className={styles.personTitle}>Environment</p>
        {ENVIRONMENTS.map((item) =>
          item.key === environment ? (
            <span key={item.key} className={styles.envRow} aria-current="true">
              <span className={styles.envName}>
                <span className={styles.envDot} data-env={item.key} />
                <strong>{item.label}</strong>
                <Check size={14} aria-hidden="true" />
              </span>
              <small>You are here · {item.hint}</small>
            </span>
          ) : (
            <a
              key={item.key}
              href={environmentHref(item.host, pathname, search)}
              className={styles.envRow}
              onClick={close}
            >
              <span className={styles.envName}>
                <span className={styles.envDot} data-env={item.key} />
                <strong>{item.label}</strong>
                <ExternalLink size={12} aria-hidden="true" />
              </span>
              <small>
                {item.hint} · opens this page there; its own sign-in
              </small>
            </a>
          ),
        )}
        <Link
          href="/usage?env=all"
          className={styles.personFoot}
          prefetch={false}
          onClick={close}
        >
          Usage & cost: every environment this Admin may read
        </Link>
      </div>
    </span>
  );
}
