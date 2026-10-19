"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { FeatureLoading } from "../feature-loading";
import { accountRedirect } from "./settings-sections";

/**
 * /account (and /account#profile, /account#billing, ?section=…) now lives in
 * Settings (20 Oct). The section is in the address's hash, which only the
 * browser sees, so the move happens here.
 */
export function AccountRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(
      accountRedirect(window.location.hash, window.location.search),
    );
  }, [router]);
  return <FeatureLoading />;
}
