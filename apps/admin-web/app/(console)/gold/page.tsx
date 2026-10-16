import Link from "next/link";
import { Star } from "lucide-react";
import { GoldReviewRows } from "./gold-review-rows";

import { when } from "@/app/calls/call-data";
import {
  GAP_TYPES,
  normalizeGold,
  sectionLabel,
  share,
} from "@/app/calls/labels-data";
import { REPORT_SKILLS } from "@/app/calls/report-pillars";
import { adminRead } from "@/app/lib/server-api";
import {
  Badge,
  Empty,
  Kpi,
  Meter,
  Page,
  PageHeader,
  Panel,
  Table,
  Tiles,
  Unavailable,
  Why,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const SKILL = Object.fromEntries(REPORT_SKILLS) as Record<string, string>;

/**
 * Dipak's gold set: calls labelled with what the right report would say, and
 * how the AI's reports agree with those labels per pillar, per skill and per
 * prompt version. Internal reviewer agreement for improving prompts; never an
 * official score (AC-SVAL) and never shown to reps.
 */
export default async function GoldPage() {
  const result = await adminRead("/v1/admin/conversation/gold", normalizeGold);
  const gold = result.ok ? result.data : null;
  const compared =
    gold?.skills.reduce((sum, row) => sum + row.compared, 0) ?? 0;
  const agreed = gold?.skills.reduce((sum, row) => sum + row.agreed, 0) ?? 0;
  const verdicts = gold?.pillars.reduce(
    (sum, row) => ({
      correct: sum.correct + row.correct,
      total: sum.total + row.correct + row.partly + row.wrong,
    }),
    { correct: 0, total: 0 },
  );
  return (
    <Page>
      <PageHeader
        title="Gold set"
        context={["What the right report would say, and how the AI compares"]}
        actions={<Badge tone="warn">Internal · not an official score</Badge>}
      />
      <GoldReviewRows />
      {!result.ok ? (
        <Unavailable title="The gold set" reason={result.error} />
      ) : null}
      {gold ? (
        <>
          <Tiles label="Gold set">
            <Kpi label="Gold calls" value={gold.calls.length} />
            <Kpi
              label="Skill agreement"
              value={share(agreed, compared)}
              note={`${agreed} of ${compared} skill states match`}
            />
            <Kpi
              label="Sections judged correct"
              value={share(verdicts?.correct ?? 0, verdicts?.total ?? 0)}
              note={`${verdicts?.total ?? 0} verdicts`}
            />
            <Kpi
              label="Training · test calls"
              value={`${gold.dataUse.training} · ${gold.dataUse.test}`}
            />
          </Tiles>
          <p className="sr-only">{gold.note}</p>
          {gold.calls.length === 0 && (verdicts?.total ?? 0) === 0 ? (
            <Panel title="No labels yet">
              <Empty
                icon={Star}
                title="Start the gold set from a call"
                text="Open a call in Calls, choose Review (V), and save a gold label: the right focus, root cause, coaching and skill states. Verdicts on each pillar count here too."
                action={{ href: "/calls", label: "Go to Calls" }}
              />
            </Panel>
          ) : (
            <>
              <Panel
                title="By prompt version"
                tools={
                  <Why
                    detail={gold.note}
                    more="Skill agreement compares the AI's skill state with the gold state, skill by skill, on the run the gold label names. Verdicts are reviewers' judgements of each report section."
                  />
                }
              >
                <Table label="Agreement by prompt version">
                  <thead>
                    <tr>
                      <th scope="col">Prompt</th>
                      <th scope="col" data-num="">
                        Skill agreement
                      </th>
                      <th scope="col" data-num="">
                        Correct
                      </th>
                      <th scope="col" data-num="">
                        Partly
                      </th>
                      <th scope="col" data-num="">
                        Wrong
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {gold.byPrompt.map((row) => (
                      <tr key={row.prompt}>
                        <th scope="row">{row.prompt}</th>
                        <td data-num="">
                          {share(row.agreed, row.compared)}{" "}
                          <small>
                            ({row.agreed}/{row.compared})
                          </small>
                        </td>
                        <td data-num="">{row.correct}</td>
                        <td data-num="">{row.partly}</td>
                        <td data-num="">{row.wrong}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Panel>
              <Panel title="By pillar and section">
                <Table label="Verdicts by section">
                  <thead>
                    <tr>
                      <th scope="col">Section</th>
                      <th scope="col">Share correct</th>
                      <th scope="col" data-num="">
                        Correct
                      </th>
                      <th scope="col" data-num="">
                        Partly
                      </th>
                      <th scope="col" data-num="">
                        Wrong
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {gold.pillars.map((row) => {
                      const total = row.correct + row.partly + row.wrong;
                      return (
                        <tr key={row.section}>
                          <th scope="row">{sectionLabel(row.section)}</th>
                          <td>
                            <Meter
                              value={row.correct}
                              max={total}
                              label={`${share(row.correct, total)} correct`}
                            />
                          </td>
                          <td data-num="">{row.correct}</td>
                          <td data-num="">{row.partly}</td>
                          <td data-num="">{row.wrong}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              </Panel>
              <Panel
                title="By skill"
                sub="the AI's state against the gold state"
              >
                <Table label="Skill agreement">
                  <thead>
                    <tr>
                      <th scope="col">Skill</th>
                      <th scope="col">Agreement</th>
                      <th scope="col" data-num="">
                        Matched
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {gold.skills.map((row) => (
                      <tr key={row.skill}>
                        <th scope="row">{SKILL[row.skill] ?? row.skill}</th>
                        <td>
                          <Meter
                            value={row.agreed}
                            max={row.compared}
                            label={`${share(row.agreed, row.compared)} agree`}
                          />
                        </td>
                        <td data-num="">
                          {row.agreed}/{row.compared}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Panel>
              <Panel title="Gold calls" sub={`${gold.calls.length}`}>
                <Table label="Gold calls">
                  <thead>
                    <tr>
                      <th scope="col">Call</th>
                      <th scope="col">Focus</th>
                      <th scope="col">Root cause</th>
                      <th scope="col">Prompt</th>
                      <th scope="col">Use</th>
                      <th scope="col">Labelled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gold.calls.map((call) => (
                      <tr key={call.recordingId}>
                        <th scope="row">
                          <Link
                            href={`/calls/${call.recordingId}${call.runId ? `?run=${call.runId}` : ""}`}
                          >
                            {call.recordingId.slice(0, 8)}
                          </Link>
                        </th>
                        <td>{SKILL[String(call.value.focus)] ?? "–"}</td>
                        <td>
                          {typeof call.value.root_cause === "string"
                            ? (GAP_TYPES.find(
                                (gap) => gap.value === call.value.root_cause,
                              )?.label ??
                              call.value.root_cause.replace(/_/g, " "))
                            : "–"}
                        </td>
                        <td>{call.prompt ?? "–"}</td>
                        <td>
                          {call.dataUse ? (
                            <Badge tone="accent">{call.dataUse}</Badge>
                          ) : (
                            "–"
                          )}
                        </td>
                        <td>{when(call.labelledAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Panel>
            </>
          )}
        </>
      ) : null}
    </Page>
  );
}
