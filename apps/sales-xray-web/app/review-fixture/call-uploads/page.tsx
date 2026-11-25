import { Suspense } from "react";
import { notFound } from "next/navigation";
import { CallUploadsPreview } from "./preview";
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Suspense fallback={null}>
      <CallUploadsPreview />
    </Suspense>
  );
}
