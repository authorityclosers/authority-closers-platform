import { notFound } from "next/navigation";
import type { SalesReport, Transcript } from "../../../report-contract";
import { StoryShellPreview } from "../story/preview";
import callB from "../story/fictional-call-b.json";

/**
 * Today's real pipeline output (no story fields, every skill only
 * "observed") on the corpus's invented call B, to check honest gaps.
 */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <StoryShellPreview
      fixture={{
        report: callB.report as unknown as SalesReport,
        transcript: callB.transcript as unknown as Transcript,
        title: "Brindle Cart · discovery call (invented script)",
        language: "English",
        speakers: {
          seller: "speaker_0",
          sellerName: "Sela",
          prospect: "speaker_1",
          prospectName: "Daryl Pell",
        },
      }}
    />
  );
}
