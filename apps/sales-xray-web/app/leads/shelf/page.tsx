import { Suspense } from "react";

import { ShelfRoute, ShelfSkeleton } from "./shelf-page";

export default function Page() {
  return (
    <Suspense fallback={<ShelfSkeleton />}>
      <ShelfRoute />
    </Suspense>
  );
}
