import { Suspense } from "react";
import { notFound } from "next/navigation";
import { CaptureGuardPreview } from "./preview";
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Suspense fallback={null}>
      <CaptureGuardPreview />
    </Suspense>
  );
}
