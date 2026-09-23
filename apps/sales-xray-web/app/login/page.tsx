"use client";

import { AccountAuth } from "../account-auth";

export default function LoginPage() {
  return (
    <AccountAuth
      onAuthenticated={() => {
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- A confirmed session needs a fresh same-origin document.
        window.location.assign("/");
      }}
    />
  );
}
