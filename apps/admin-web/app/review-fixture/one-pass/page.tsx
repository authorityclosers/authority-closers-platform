import { notFound } from "next/navigation";

import {
  CompareDetail,
  CompareTable,
  SummaryTiles,
} from "../../sales-xray/one-pass-compare";
import {
  normalizeCompareList,
  normalizeCompared,
  normalizePipeline,
} from "../../sales-xray/one-pass-data";
import { PipelineSwitch } from "../../sales-xray/one-pass-switch";
import { Page, PageHeader, Panel } from "../../ui/kit";
import {
  fixtureCompared,
  fixtureList,
  fixturePipeline,
} from "./one-pass-fixture";

/**
 * Local review of the one-pass trial screens with fictional data (no API, no
 * call, no account), for screenshots at phone and desktop widths. Never in a
 * production build.
 */
export default function OnePassFixturePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  const settings = normalizePipeline(fixturePipeline);
  const list = normalizeCompareList(fixtureList);
  return (
    <Page wide>
      <PageHeader title="One pass" context={["Fixture: fictional data"]} />
      <Panel title="Analysis pipeline" sub="development · revision 2">
        <PipelineSwitch settings={settings} />
      </Panel>
      <SummaryTiles title="Fictional benchmark set" summary={list.bench} />
      <Panel title="Compared calls" sub="1 call">
        <CompareTable items={list.items} />
      </Panel>
      <CompareDetail data={normalizeCompared(fixtureCompared)} />
    </Page>
  );
}
