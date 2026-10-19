"use client";

import { useEffect, useState } from "react";

import { CallMap } from "../../calls/call-map";
import { normalizeMap, type CallMapData } from "../../calls/call-map-data";
import { EngineObjectsView } from "../../calls/engine-objects";
import {
  normalizeEngineObjects,
  type EngineObjects,
} from "../../calls/engine-objects-data";
import { Page, PageHeader } from "../../ui/kit";

// The screenshot harness answers these two reads with a dev call's real data;
// without it the page stays empty. Never in a production build (page.tsx).
const CALL = "00000000-0000-4000-8000-0000000000aa";

export function CallMapFixture() {
  const [map, setMap] = useState<CallMapData | null>(null);
  const [objects, setObjects] = useState<EngineObjects | null>(null);
  useEffect(() => {
    const base = `/v1/admin/conversation/calls/${CALL}`;
    fetch(`${base}/data-map`)
      .then((r) => r.json())
      .then((raw: unknown) => setMap(normalizeMap(raw)))
      .catch(() => undefined);
    fetch(`${base}/data-objects`)
      .then((r) => r.json())
      .then((raw: unknown) => setObjects(normalizeEngineObjects(raw)))
      .catch(() => undefined);
  }, []);
  return (
    <Page>
      <PageHeader
        title="Pipeline map"
        context={map ? [map.workspace, map.state] : []}
      />
      {map ? <CallMap map={map} /> : null}
      {objects ? <EngineObjectsView data={objects} /> : null}
    </Page>
  );
}
