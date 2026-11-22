"use client";

/**
 * The end of a lead's call report (round-2 board 1, option B, 20 Nov 2026): the report
 * ends in the next action, "Call next lead", with the way back to the lead it was for.
 * Call next lead opens Leads on To call, where the one Call button rings the next lead.
 */
import Link from "next/link";
import { ArrowLeft, PhoneCall } from "lucide-react";
import styles from "./wrap-up.module.css";

export function ReportCallNext({
  leadId,
  name,
}: {
  leadId: string;
  name: string;
}) {
  const first = name.split(" ")[0] || name;
  return (
    <nav className={styles.reportNext} aria-label="After this report">
      <Link
        href="/leads?view=to_call"
        className={styles.primary}
        data-sx-feature="report_call_next"
      >
        <PhoneCall size={20} aria-hidden="true" />
        Call next lead
      </Link>
      <Link
        href={`/leads?lead=${encodeURIComponent(leadId)}`}
        className={styles.secondary}
        data-sx-feature="report_back_to_lead"
      >
        <ArrowLeft size={20} aria-hidden="true" />
        Back to {first}
      </Link>
    </nav>
  );
}
