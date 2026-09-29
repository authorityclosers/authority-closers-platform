"use client";

import { AccountAuth } from "../account-auth";

/** Return to a same-origin app path after sign-in; anything else goes home. */
function safeNextPath(search: string): string {
  const next = new URLSearchParams(search).get("next");
  return next &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.includes("\\") &&
    !next.startsWith("/login")
    ? next
    : "/dashboard";
}

export default function LoginPage() {
  return (
    <AccountAuth
      onAuthenticated={() => {
        window.location.assign(safeNextPath(window.location.search));
      }}
    />
  );
}
