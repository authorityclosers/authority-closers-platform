"use client";

import { useEffect, useRef, useState } from "react";
import {
  Building2,
  ChevronRight,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { PlatformMark } from "@ac/ui";
import {
  loadPlatformIdentity,
  readPlatformJson,
  type PlatformIdentity,
} from "@ac/operations-web/platform-identity";
import { z } from "zod";
import styles from "./platform-console.module.css";

const tenantsSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    next_after_id: z.uuid().nullable(),
    tenants: z
      .array(
        z
          .object({
            tenant_id: z.uuid(),
            name: z.string().min(1).max(200),
            status: z.enum(["active", "suspended", "deleted"]),
            kind: z.enum(["platform", "academy"]),
          })
          .strict(),
      )
      .max(100),
  })
  .strict()
  .refine(
    (value) =>
      new Set(value.tenants.map((row) => row.tenant_id)).size ===
      value.tenants.length,
  );
type Inventory = z.infer<typeof tenantsSchema>;
const permissionNames: Record<PlatformIdentity["permissions"][number], string> =
  {
    platform_access_manage: "Manage platform access",
    platform_tenants_read: "View academies",
    platform_catalog_read: "View platform catalog",
    platform_catalog_write: "Edit platform catalog",
    platform_catalog_publish: "Publish platform catalog",
  };

export function PlatformConsole() {
  const [identity, setIdentity] = useState<PlatformIdentity | null>(null);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const current = useRef<AbortController | null>(null);
  const navigating = useRef(false);

  async function readInventory(
    subject: PlatformIdentity,
    controller: AbortController,
    after: string | null = null,
  ) {
    const response = await fetch(
      "/v1/platform/tenants" +
        (after ? "?after_id=" + encodeURIComponent(after) : ""),
      {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
        headers: { accept: "application/json" },
      },
    );
    if (!response.ok) throw new Error();
    const result = tenantsSchema.parse(
      await readPlatformJson(response, 131072),
    );
    if (
      result.person_id !== subject.personId ||
      result.session_id !== subject.sessionId
    )
      throw new Error();
    return result;
  }

  useEffect(() => {
    const controller = new AbortController();
    current.current = controller;
    void (async () => {
      const verified = await loadPlatformIdentity({
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!verified) {
        setError(
          "Your platform access could not be verified. Try again or sign in with an assigned account.",
        );
        return;
      }
      setIdentity(verified);
      if (verified.permissions.includes("platform_tenants_read")) {
        const result = await readInventory(verified, controller);
        if (!controller.signal.aborted) setInventory(result);
      }
    })()
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "Academies could not be loaded. Check your connection and try again.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => {
      controller.abort();
      current.current?.abort();
      current.current = null;
    };
  }, [retry]);

  async function nextPage() {
    if (pending || navigating.current || !identity || !inventory?.next_after_id)
      return;
    navigating.current = true;
    setPending(true);
    setError("");
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    try {
      // Revalidate identity and the exact capability; never reuse a stale account view.
      const fresh = await loadPlatformIdentity({ signal: controller.signal });
      if (
        !fresh ||
        fresh.personId !== identity.personId ||
        fresh.sessionId !== identity.sessionId ||
        !fresh.permissions.includes("platform_tenants_read")
      )
        throw new Error();
      const result = await readInventory(
        fresh,
        controller,
        inventory.next_after_id,
      );
      if (!controller.signal.aborted) setInventory(result);
    } catch {
      if (!controller.signal.aborted) {
        setInventory(null);
        setError("Access or connection changed. Reload to check your account.");
      }
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        navigating.current = false;
      }
    }
  }

  async function signOut() {
    if (pending || navigating.current) return;
    navigating.current = true;
    setPending(true);
    setError("");
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    try {
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
      });
      if (!response.ok) throw new Error();
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Confirmed sign-out must discard the privileged document and route cache.
      if (!controller.signal.aborted) window.location.assign("/login");
    } catch {
      if (!controller.signal.aborted)
        setError("Sign-out was not confirmed. Please try again.");
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        navigating.current = false;
      }
    }
  }

  function reload() {
    if (pending) return;
    current.current?.abort();
    navigating.current = false;
    setIdentity(null);
    setInventory(null);
    setError("");
    setPending(true);
    setRetry((value) => value + 1);
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <a href="/platform" className={styles.brand}>
          <PlatformMark />
          <span>
            Cohorva<small>Platform Admin</small>
          </span>
        </a>
        {identity ? (
          <button disabled={pending} onClick={() => void signOut()}>
            <LogOut size={17} aria-hidden="true" />
            Sign out
          </button>
        ) : (
          <a href="/login">Sign in</a>
        )}
      </header>
      <main id="admin-content" className={styles.main}>
        <div className={styles.heading}>
          <div>
            <p>PLATFORM WORKSPACE</p>
            <h1>Your academies, in one place.</h1>
            <span>
              Manage the platform. Keep each academy’s teaching space its own.
            </span>
          </div>
          <button
            onClick={reload}
            disabled={pending}
            aria-label="Reload platform access and academies"
          >
            <RefreshCw size={18} aria-hidden="true" />
            Refresh
          </button>
        </div>
        {pending && <p role="status">Checking your platform workspace…</p>}
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}
        {identity && (
          <div className={styles.grid}>
            <section className={styles.panel} aria-labelledby="academy-heading">
              <div className={styles.panelHeading}>
                <Building2 size={22} aria-hidden="true" />
                <h2 id="academy-heading">Academies</h2>
              </div>
              {!identity.permissions.includes("platform_tenants_read") ? (
                <p>
                  Your current assignment does not include the academy
                  directory.
                </p>
              ) : inventory ? (
                <>
                  <ul className={styles.list}>
                    {inventory.tenants.map((tenant) => (
                      <li key={tenant.tenant_id}>
                        <span className={styles.academyIcon}>
                          <Building2 size={20} aria-hidden="true" />
                        </span>
                        <div>
                          <strong>{tenant.name}</strong>
                          <small>
                            {tenant.kind === "platform"
                              ? "Platform operations"
                              : "Academy workspace"}
                          </small>
                        </div>
                        <span className={styles.status}>{tenant.status}</span>
                      </li>
                    ))}
                  </ul>
                  {inventory.tenants.length === 0 && (
                    <p>No academies are available.</p>
                  )}
                  {inventory.next_after_id && (
                    <button onClick={() => void nextPage()} disabled={pending}>
                      Next academies{" "}
                      <ChevronRight size={17} aria-hidden="true" />
                    </button>
                  )}
                </>
              ) : null}
            </section>
            <aside className={styles.panel} aria-labelledby="access-heading">
              <div className={styles.panelHeading}>
                <ShieldCheck size={22} aria-hidden="true" />
                <h2 id="access-heading">Your access</h2>
              </div>
              <strong>{identity.displayName || identity.email}</strong>
              <p className={styles.email}>{identity.email}</p>
              <ul className={styles.permissions}>
                {identity.permissions.map((permission) => (
                  <li key={permission}>{permissionNames[permission]}</li>
                ))}
              </ul>
              <p className={styles.note}>
                These permissions apply to Cohorva. Teaching, learner
                enrollment, finance, and infrastructure keep their own access
                rules.
              </p>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
