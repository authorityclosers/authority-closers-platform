"use client";

import { Empty, Skeleton } from "@ac/ui/kit";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signInHref } from "../../shell/signed-out-welcome";
import { reflexRequest } from "./validation";
import styles from "./page.module.css";

/** The same 401 -> normal sign-in gate used by ConnectView. */
export default function ReflexConnectPage() {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const operation = useRef<{
    attempt: number;
    promise: Promise<string>;
  } | null>(null);
  useEffect(() => {
    let active = true;
    if (!operation.current || operation.current.attempt !== attempt) {
      const promise = (async () => {
        const body = reflexRequest(window.location.search);
        if (!body) throw new Error("invalid_request");
        const response = await fetch("/v1/auth/handoff/start", {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: {
            "content-type": "application/json",
            accept: "application/json",
          },
          body: JSON.stringify(body),
        });
        if (response.status === 401) {
          const here =
            window.location.pathname +
            window.location.search +
            window.location.hash;
          return signInHref(here);
        }
        if (!response.ok) throw new Error("handoff_failed");
        const data: unknown = await response.json();
        if (
          !data ||
          typeof data !== "object" ||
          !("url" in data) ||
          typeof data.url !== "string"
        )
          throw new Error("invalid_response");
        // The server is the destination authority. Only accept the fixed learner
        // handoff shape; neither query parameter is a redirect destination.
        const url = new URL(data.url);
        if (
          url.protocol !== "https:" ||
          url.pathname !== "/auth/handoff" ||
          url.search ||
          url.username ||
          url.password ||
          !url.hash.startsWith("#code=")
        )
          throw new Error("invalid_response");
        return url.href;
      })();
      operation.current = { attempt, promise };
    }
    operation.current.promise
      .then((url) => {
        if (active) window.location.replace(url);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="reflex-title">
        <h1 id="reflex-title">Reflex</h1>
        {failed ? (
          <>
            <Empty
              icon={ArrowRight}
              title="Couldn't open Reflex"
              text="Try again when you're ready."
              action={{
                label: "Try again",
                onClick: () => {
                  setFailed(false);
                  setAttempt((value) => value + 1);
                },
              }}
            />
            <Link className={styles.back} href="/dashboard">
              Back to Sales X-Ray
            </Link>
          </>
        ) : (
          <div role="status" aria-live="polite">
            <p>Opening Reflex…</p>
            <Skeleton width="70%" height={12} />
          </div>
        )}
      </section>
    </main>
  );
}
