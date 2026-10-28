"use client";
import { PageSkeleton } from "@ac/ui/kit";
import { activePlace } from "./places";
export function RouteLoading({ path = "/home" }: { path?: string }) {
  const place = activePlace(path);
  return (
    <div role="status" aria-label="Loading your page">
      <PageSkeleton
        instant
        variant={
          place === "/home"
            ? "dashboard"
            : place === "/profile"
              ? "account"
              : "list"
        }
      />
    </div>
  );
}
