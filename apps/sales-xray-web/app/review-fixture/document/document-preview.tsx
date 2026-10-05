"use client";

import { ReportModes } from "../../report-modes";
import { syntheticEvidence, syntheticReport } from "../report/synthetic-report";
import styles from "../report/synthetic-report-preview.module.css";

const callId = "00000000-0000-4000-8000-000000000002";
const quotes = Object.values(syntheticEvidence);
const VOICES = ["fictional-seller", "fictional-buyer"];

export function DocumentPreview() {
  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.heading}>
          <div>
            <h1>Fictional document review</h1>
            <p>
              Invented dialogue for print and accessibility checks. No recording
              or validated coaching result exists.
            </p>
          </div>
        </header>
        <ReportModes
          initialView="document"
          boundCallId={callId}
          documentData={{
            report: syntheticReport,
            transcript: {
              source_sha256: syntheticReport.source_sha256,
              revision: syntheticReport.transcript_revision,
              timebase_id: "synthetic",
              duration_ms: 35000,
              segments: quotes.map((e, i) => ({
                id: e.segment_id,
                speaker_id: VOICES[i % 2],
                start_ms: e.start_ms,
                end_ms: e.end_ms,
                text: e.quote,
              })),
            },
            callRecord: {
              version: "call-record/1",
              numbers: {
                duration_ms: 35000,
                overlaps: 1,
                speakers: [
                  {
                    speaker_id: VOICES[0],
                    talk_ms: 14000,
                    talk_share: 0.45,
                    questions: 2,
                    longest_monologue_ms: 6000,
                  },
                  {
                    speaker_id: VOICES[1],
                    talk_ms: 17000,
                    talk_share: 0.55,
                    questions: 0,
                    longest_monologue_ms: 8000,
                  },
                ],
              },
              facts: [
                {
                  statement: "The fictional buyer asked not to be followed up.",
                  evidence: [syntheticEvidence.boundary],
                  tag: "next_step",
                },
              ],
              tags: null,
              call_type: "first_meeting",
            },
            speakerNames: {
              [VOICES[0]]: "Fictional seller",
              [VOICES[1]]: "Fictional buyer",
            },
            title: "Fictional seller — sample call report",
            workspaceName: "Synthetic display only",
            repName: "Fictional seller",
            analysisBasis: {
              transcriptRevision: syntheticReport.transcript_revision,
            },
          }}
          panels={[
            {
              id: "overview",
              label: "Overall assessment",
              content: (
                <>
                  <p>{syntheticReport.summary}</p>
                  <p>{syntheticReport.verdict}</p>
                </>
              ),
            },
            {
              id: "skills",
              label: "Capability evidence",
              content: (
                <table>
                  <thead>
                    <tr>
                      <th>Capability</th>
                      <th>Observation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {syntheticReport.dimensions.map((d) => (
                      <tr key={d.dimension_id}>
                        <td>{d.label}</td>
                        <td>{d.observation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ),
            },
            {
              id: "strengths",
              label: "What the seller does well",
              content: (
                <>
                  {syntheticReport.strengths.map((f) => (
                    <div key={f.title}>
                      <h3>{f.title}</h3>
                      <p>{f.explanation}</p>
                      {f.evidence.map((e) => (
                        <blockquote key={e.segment_id}>{e.quote}</blockquote>
                      ))}
                    </div>
                  ))}
                </>
              ),
            },
            {
              id: "improvements",
              label: "Development areas",
              content: (
                <>
                  {syntheticReport.improvements.map((f) => (
                    <div key={f.title}>
                      <h3>{f.title}</h3>
                      <p>{f.explanation}</p>
                      {f.evidence.map((e) => (
                        <blockquote key={e.segment_id}>{e.quote}</blockquote>
                      ))}
                    </div>
                  ))}
                </>
              ),
            },
            {
              id: "moments",
              label: "Source moments",
              content: (
                <table>
                  <thead>
                    <tr>
                      <th>Moment</th>
                      <th>Source quote</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotes.map((e, i) => (
                      <tr key={e.segment_id}>
                        <td>{i + 1}</td>
                        <td>{e.quote}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ),
            },
            {
              id: "next-call-plan",
              label: "Next-call plan",
              content: (
                <p>
                  The fictional buyer did not agree to another step. The seller
                  acknowledged this and did not schedule a follow-up.
                </p>
              ),
            },
            {
              id: "transcript",
              label: "Transcript appendix",
              content: (
                <>
                  {quotes.map((e) => (
                    <p key={e.segment_id}>
                      {e.start_ms / 1000}s: “{e.quote}”
                    </p>
                  ))}
                </>
              ),
            },
          ]}
        />
      </div>
    </main>
  );
}
