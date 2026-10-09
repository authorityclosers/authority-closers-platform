"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ConnectionNotice } from "../connection-notice";
export function DashboardRetry() {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  return (
    <ConnectionNotice
      title="Some numbers did not load"
      message="Some dashboard numbers could not load. The rest of the page still works."
      failures={attempt + 1}
      onRetry={() => {
        setAttempt((value) => value + 1);
        router.refresh();
      }}
    />
  );
}
