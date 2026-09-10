"use client";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { AcademyMark } from "@ac/ui";
import {
  AdminSessionProvider,
  useAdminSession,
} from "@ac/operations-web/session";
function Workspace({ children }: { children: ReactNode }) {
  const state = useAdminSession();
  const [error, setError] = useState("");
  async function signOut() {
    try {
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error();
      window.location.assign("/login");
    } catch {
      setError("Sign-out was not confirmed. Please try again.");
    }
  }
  return (
    <div className="coach-workspace">
      <header className="coach-header">
        <Link href="/studio/programs" className="coach-brand">
          <AcademyMark width={38} height={38} aria-hidden="true" />
          <span>
            Academy Studio<small>by Cohorva</small>
          </span>
        </Link>
        <nav aria-label="Academy Studio">
          <Link href="/studio/programs">Courses</Link>
        </nav>
        <div className="coach-account">
          <span>
            {state.status === "ready"
              ? (state.session.displayName ?? state.session.email)
              : "Your workspace"}
          </span>
          <button onClick={signOut}>Sign out</button>
        </div>
      </header>
      {error && <p role="alert">{error}</p>}
      <main id="admin-content" className="coach-content">
        {children}
      </main>
    </div>
  );
}
export function CoachShell({ children }: { children: ReactNode }) {
  return (
    <AdminSessionProvider>
      <Workspace>{children}</Workspace>
    </AdminSessionProvider>
  );
}
