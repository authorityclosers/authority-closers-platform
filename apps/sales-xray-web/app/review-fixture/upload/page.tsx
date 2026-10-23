import { notFound } from "next/navigation";

import { UploadPreview, type UploadStep } from "./preview";

/**
 * The real New analysis upload (acquisition-studio.tsx) with fictional answers, for
 * tutorials ("Upload a recording you already have"). `?step=picked` has a recording
 * chosen, `?step=details` the "Verify and continue" step with the terms ticked,
 * `?step=analysing` the call being analysed; otherwise the empty upload page.
 * Each screen is its own step: "Analyse my call" stays on the details step here.
 * Nothing leaves the browser. Never in a production build.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { step } = await searchParams;
  const shown: UploadStep =
    step === "picked" || step === "details" || step === "analysing"
      ? step
      : "start";
  return <UploadPreview key={shown} step={shown} />;
}
