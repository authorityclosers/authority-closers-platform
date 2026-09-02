"use client";

import { useEffect } from "react";

export function PwaRegister() {
  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" ||
      !("serviceWorker" in navigator) ||
      (window.location.protocol !== "https:" &&
        window.location.hostname !== "localhost" &&
        window.location.hostname !== "127.0.0.1")
    ) {
      return;
    }

    // `updateViaCache: "none"` lets the browser see a changed worker
    // promptly. The worker deliberately does not force a reload, so a dirty
    // learner draft cannot be interrupted by an update.
    void navigator.serviceWorker
      .register("/sw.js", {
        scope: "/",
        updateViaCache: "none",
      })
      .catch(() => {
        // The browser remains usable when service-worker storage or policy is
        // unavailable (private browsing, blocked storage, or an HTTP host).
      });
  }, []);

  return null;
}
