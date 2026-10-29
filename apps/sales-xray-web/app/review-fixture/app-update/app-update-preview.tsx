"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { UpdateCard } from "../../app-compatibility-provider";

/**
 * The update card as the phone app shows it when its version is below the
 * minimum (the default) or below the recommended one (?state=recommended),
 * without changing any server's settings.
 */
function Preview() {
  const recommended = useSearchParams().get("state") === "recommended";
  return <UpdateCard required={!recommended} onLater={() => {}} />;
}

export function AppUpdatePreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
