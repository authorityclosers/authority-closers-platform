"use client";

import { AccountAuth } from "../account-auth";

/** Return to a same-origin app path after sign-in; anything else goes home. */
function safeNextPath(search: string): string {
  const next = new URLSearchParams(search).get("next");
  try {
    const url = new URL(next ?? "", window.location.origin);
    if (
      next?.startsWith("/") &&
      url.origin === window.location.origin &&
      !url.pathname.startsWith("/login")
    )
      return `${url.pathname}${url.search}${url.hash}`;
  } catch {}
  return "/dashboard";
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
