import { notFound } from "next/navigation";
import { PillarsPreview } from "./pillars-preview";
import { v8Report } from "./v8-report";

/**
 * A report whose analysis supplies the six pillars itself (report-pillars/1,
 * H's fictional v8 projection): free stage names, before/after in words,
 * buying signals, the deal block. Fictional call, no provider.
 */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  const { report, transcript } = v8Report();
  return (
    <PillarsPreview
      nativeFixture={{
        report,
        transcript,
        title: "Qivra Works · discovery call (fictional v8 output)",
        language: "English",
        speakers: {
          seller: "speaker_0",
          sellerName: "Sela",
          prospect: "speaker_1",
          prospectName: "Daro",
        },
      }}
    />
  );
}
