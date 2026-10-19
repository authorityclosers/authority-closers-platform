import { ClipboardCheck } from "lucide-react";

import { adminRead } from "@/app/lib/server-api";
import { PipelineEditor } from "@/app/settings/pipeline-editor";
import styles from "@/app/settings/pipeline-editor.module.css";
import {
  TARGET_LABEL,
  normalizePipelineSettings,
} from "@/app/settings/review-pipelines-data";
import { Empty, Page, PageHeader, Panel, Unavailable, Why } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const SHOW_LABEL: Record<string, string> = {
  evidence: "the evidence quotes",
  transcript_window: "the transcript around it",
  coaching_point: "the coaching point",
  voice: "voice measures",
};

/**
 * Admin → Settings → Review pipelines (Review 2.0, slice 3): each pipeline's
 * questions and sample, edited from the primitives. A save is a new version.
 */
export default async function ReviewPipelinesPage() {
  const result = await adminRead(
    "/v1/admin/conversation/review/pipelines",
    normalizePipelineSettings,
  );
  return (
    <Page>
      <PageHeader
        title="Review pipelines"
        back={{ href: "/settings", label: "All settings" }}
        context={[
          "What gold reviewers judge and the questions they answer. A save makes a new version; earlier answers keep theirs.",
        ]}
      />
      {!result.ok ? (
        <Unavailable title="Review pipelines" reason={result.error} />
      ) : result.data.pipelines.length ? (
        result.data.pipelines.map((pipeline) => (
          <Panel
            key={pipeline.key}
            title={pipeline.title}
            sub={`Version ${pipeline.version}${pipeline.saved ? "" : " · default, never edited"}`}
            tools={
              <Why detail="A pipeline is built from primitives: sample (which calls and items), show (what the reviewer sees), ask (the questions), reconcile (a third reviewer when two disagree) and measure (agreement, shown in Analysis health). Questions and the sample size are editable now; the rest follows as Review runs more of them." />
            }
          >
            <dl className={styles.primitives}>
              <div>
                <dt>Judges</dt>
                <dd>
                  {pipeline.targets
                    .map((target) => TARGET_LABEL[target] ?? target)
                    .join(", ") || "—"}
                </dd>
              </div>
              <div>
                <dt>Shows</dt>
                <dd>
                  {pipeline.show
                    .map((item) => SHOW_LABEL[item] ?? item)
                    .join(", ") || "—"}
                </dd>
              </div>
              <div>
                <dt>Reconcile</dt>
                <dd>
                  {pipeline.reconcileReviewers
                    ? `${pipeline.reconcileReviewers} reviewers, then a third if they disagree`
                    : "—"}
                </dd>
              </div>
            </dl>
            <PipelineEditor
              pipeline={pipeline}
              limits={result.data.limits}
              canEdit={result.data.canEdit}
            />
          </Panel>
        ))
      ) : (
        <Panel title="Review pipelines">
          <Empty icon={ClipboardCheck} title="No review pipelines" />
        </Panel>
      )}
    </Page>
  );
}
