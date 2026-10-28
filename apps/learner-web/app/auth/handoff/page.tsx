"use client";

import { Skeleton } from "@ac/ui/kit";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import {
  HANDOFF_VERIFIER_KEY,
  isHandoffReturnPath,
} from "../../lib/cross-app-handoff";
import { ReflexMark } from "../../shell/reflex-mark";
import styles from "../../components/reflex-login.module.css";

const EXPIRED = "/login?handoff=expired";

export default function HandoffPage() {
  const router = useRouter();
  const operation = useRef<Promise<string> | null>(null);
  useEffect(() => {
    let active = true;
    if (!operation.current) {
      operation.current = (async () => {
        const fragment = new URLSearchParams(window.location.hash.slice(1));
        const code = fragment.get("code");
        // Erase credentials before storage access, requests or any navigation.
        window.history.replaceState(
          window.history.state,
          "",
          window.location.pathname + window.location.search,
        );
        const verifier = sessionStorage.getItem(HANDOFF_VERIFIER_KEY);
        try {
          if (
            !code ||
            code.length > 4096 ||
            fragment.getAll("code").length !== 1 ||
            !verifier
          )
            return EXPIRED;
          const response = await fetch("/v1/auth/handoff/redeem", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
            headers: {
              "content-type": "application/json",
              accept: "application/json",
            },
            body: JSON.stringify({ code, verifier }),
          });
          if (!response.ok) return EXPIRED;
          const data: unknown = await response.json();
          if (
            !data ||
            typeof data !== "object" ||
            !("return_path" in data) ||
            !isHandoffReturnPath(data.return_path) ||
            !("result" in data)
          )
            return EXPIRED;
          if (data.result === "success") return data.return_path;
          if (
            data.result === "consent_required" ||
            data.result === "consent_update_required"
          )
            return `/consent/renewal?${new URLSearchParams({ return: data.return_path })}`;
          return EXPIRED;
        } finally {
          // StrictMode reattaches to this same promise; keep the verifier until
          // the one redeem request settles. Never remove a newer attempt's value.
          if (sessionStorage.getItem(HANDOFF_VERIFIER_KEY) === verifier)
            sessionStorage.removeItem(HANDOFF_VERIFIER_KEY);
        }
      })().catch(() => EXPIRED);
    }
    void operation.current.then((destination) => {
      if (active) router.replace(destination);
    });
    return () => {
      active = false;
    };
  }, [router]);
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-label="Opening Reflex">
        <ReflexMark size={40} />
        <h1>Reflex</h1>
        <p role="status">Opening Reflex…</p>
        <Skeleton width="70%" height={12} />
      </section>
    </main>
  );
}
