import { Handshake } from "lucide-react";

import { Empty, Page, PageHeader, Panel } from "@/app/ui/kit";

/**
 * Deal outcomes come only from people: a rep or manager taps won, lost (with a
 * reason), follow-up (with a date) or no decision on a call. AI never infers
 * them. The store and its read API belong to the Report strike (AUT-1677) and
 * aren't ready, so this page says so instead of showing invented numbers.
 */
export default function OutcomesPage() {
  return (
    <Page>
      <PageHeader
        title="Deal outcomes"
        context={["Won, lost and follow-ups that reps record on their calls"]}
      />
      <Panel title="Not recording yet">
        <Empty
          icon={Handshake}
          title="Outcomes aren't being recorded yet"
          text="Reps will set an outcome on each call with one tap: won, lost (with a reason), follow-up (with a date) or no decision, plus an optional deal value. Once that store ships, this page shows outcomes by organisation, rep and week, and how they line up with each call's report. Outcomes are never guessed from the AI."
        />
      </Panel>
    </Page>
  );
}
