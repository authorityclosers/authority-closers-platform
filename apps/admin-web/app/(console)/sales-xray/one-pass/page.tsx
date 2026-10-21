import { FlaskConical } from "lucide-react";
import Link from "next/link";

import { adminRead } from "@/app/lib/server-api";
import { CompareTable, SummaryTiles } from "@/app/sales-xray/one-pass-compare";
import {
  inr,
  normalizeCompareList,
  normalizePipeline,
  normalizeTranscription,
  took,
} from "@/app/sales-xray/one-pass-data";
import { PipelineSwitch } from "@/app/sales-xray/one-pass-switch";
import { TranscriptionSwitch } from "@/app/sales-xray/one-pass-transcription";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → One pass (owner, 21 Oct 2026): this environment's analysis pipeline
 * (today's; one pass for people, the owner's typed-confirm action; or both side
 * by side on development), and what the comparison shows so far: cost per
 * audio minute, quality and time, for real calls and for the fictional
 * benchmark set apart. Back to today's pipeline is one click.
 */
export default async function OnePassPage() {
  const [settings, compared, transcription] = await Promise.all([
    adminRead("/v1/admin/analysis-pipeline", normalizePipeline),
    adminRead("/v1/admin/analysis-pipeline/compare", normalizeCompareList),
    adminRead(
      "/v1/admin/analysis-pipeline/transcription",
      normalizeTranscription,
    ),
  ]);
  return (
    <Page wide>
      <PageHeader
        title="One pass"
        context={[
          "One pass: each call's deep call data and pointer review come from one strict Gemini 3.8 Flash read of the saved transcript (the owner's action). Both: the Google-only pipeline beside today's, compared (development). List-price estimates for Admin only.",
        ]}
        actions={
          <Link
            href="/ai-spend"
            className={kitStyles.button}
            data-variant="ghost"
          >
            Spend cap
          </Link>
        }
      />
      {transcription.ok ? (
        <Panel
          title="Transcription (C2)"
          sub="Production's one-pass saving: Gemini 3.1 Flash-Lite instead of Scribe, sealed, then the owner's switch"
        >
          <TranscriptionSwitch view={transcription.data} />
        </Panel>
      ) : (
        <Unavailable title="Transcription (C2)" reason={transcription.error} />
      )}
      {settings.ok ? (
        <Panel
          title="Analysis pipeline"
          sub={`${settings.data.environment} · ${
            settings.data.revision
              ? `revision ${settings.data.revision}`
              : "default"
          } · its spend cap is in AI spend (One pass)`}
        >
          <PipelineSwitch settings={settings.data} />
        </Panel>
      ) : (
        <Unavailable title="Analysis pipeline" reason={settings.error} />
      )}
      {compared.ok ? (
        <>
          <SummaryTiles title="Real calls" summary={compared.data.calls} />
          <SummaryTiles
            title="Fictional benchmark set"
            summary={compared.data.bench}
          />
          <Panel
            title="Compared calls"
            sub={`${compared.data.items.length} calls · open one for facts, scores and coaching side by side`}
          >
            {compared.data.items.length ? (
              <CompareTable items={compared.data.items} />
            ) : (
              <Empty
                icon={FlaskConical}
                title="Nothing compared yet"
                text="On development, set the pipeline to Both and raise the One pass cap in AI spend; new calls are then read both ways."
              />
            )}
          </Panel>
        </>
      ) : (
        <Unavailable title="Comparison" reason={compared.error} />
      )}
      {settings.ok && settings.data.recent.length ? (
        <Panel title="Latest one-pass runs" sub="Newest first">
          <Table label="Latest one-pass runs">
            <thead>
              <tr>
                <th scope="col">Call</th>
                <th scope="col">Result</th>
                <th scope="col">Contracts</th>
                <th scope="col">Length</th>
                <th scope="col">Time</th>
                <th scope="col">Cost</th>
              </tr>
            </thead>
            <tbody>
              {settings.data.recent.map((run) => (
                <tr key={`${run.subject}-${run.at}`}>
                  <th scope="row">
                    <Link href={`/sales-xray/one-pass/${run.subject}`}>
                      {run.source === "bench"
                        ? `Fictional ${run.subject}`
                        : run.subject.slice(0, 8)}
                    </Link>
                  </th>
                  <td>
                    <Badge
                      tone={
                        run.state === "succeeded"
                          ? "good"
                          : run.state === "failed"
                            ? "bad"
                            : "neutral"
                      }
                    >
                      {run.reason ? `${run.state}: ${run.reason}` : run.state}
                    </Badge>
                  </td>
                  <td>
                    {run.contractsOk === null ? "—" : `${run.contractsOk}/6`}
                  </td>
                  <td>{took(run.audioMs)}</td>
                  <td>{took(run.durationMs)}</td>
                  <td>{inr(run.costInr) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
    </Page>
  );
}
