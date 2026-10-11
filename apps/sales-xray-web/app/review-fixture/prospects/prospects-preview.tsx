"use client";
import { ProspectInformation } from "../../prospect-information";
import { SpeakerProfilesContext } from "../../speaker-profiles";
import { amitReport, amitTranscript } from "../report/story/amit-call";
import {
  AMIT_CALL_ID,
  AMIT_SPEAKERS,
  amitCalls,
  amitProspect,
} from "./amit-prospect";
import { syntheticProspect } from "./synthetic-prospect";
import styles from "../../prospect-information.module.css";

/** Fictional names and roles, as a person would confirm them. */
const SPEAKERS = {
  callId: AMIT_CALL_ID,
  profiles: {
    [AMIT_SPEAKERS.seller]: { name: "Arjun", role: "you", icon: null },
    [AMIT_SPEAKERS.prospect]: {
      name: "Amit Sharma",
      role: "prospect",
      icon: null,
    },
  },
  drafts: {},
  save: () => false,
  canSave: false,
  error: null,
  server: true,
} as const;

export function ProspectsPreview() {
  return (
    <main className={styles.preview}>
      <h1>Amit Sharma</h1>
      <p className={styles.note}>
        Founder · XYZ Digital — fictional prospect from the spec. No API
        requests, real customer or recording.
      </p>
      <SpeakerProfilesContext.Provider value={SPEAKERS}>
        <ProspectInformation
          prospect={amitProspect}
          calls={amitCalls}
          latest={{
            callId: AMIT_CALL_ID,
            report: amitReport,
            transcript: amitTranscript,
          }}
        />
      </SpeakerProfilesContext.Provider>
      <h2 className={styles.previewSecond}>
        A detected prospect with only one call fact
      </h2>
      <ProspectInformation prospect={syntheticProspect} />
    </main>
  );
}
