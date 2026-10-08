import { parseReportLanguage } from "./report-language";
import { ReportContractError, encodeConversationId } from "./report-contract";

type ProcessingPlanStage = {
  stage: "C2" | "C4" | "C5";
  provider: string;
  model: string;
  max_requests: number;
  privacy_revision: string;
  privacy_notice: string;
};
export type ProcessingPlan = {
  report_language?: import("./report-language").ReportLanguage;
  coaching_prompt_revision?:
    | "coaching-v1"
    | "coaching-v2"
    | "coaching-v3"
    | "coaching-v4"
    | "coaching-v5";
  id: string;
  recording_id: string;
  plan_fingerprint: string;
  privacy_revision: "sales-xray-processing-plan-v1";
  accepted: boolean;
  state: "quoted" | "active" | "held" | "completed" | "cancelled";
  cost_label: string;
  max_cost_paise: number;
  automatic_c5_repair_cost_paise: number;
  max_entitlement_seconds: number;
  expires_at_epoch: number;
  stages: ProcessingPlanStage[];
  current_stage: string | null;
  report_ready: boolean;
  report_run_id: string | null;
  automatic_progression: true;
  failure_code: string | null;
};
const PLAN_STATES = new Set([
  "quoted",
  "active",
  "held",
  "completed",
  "cancelled",
]);
const PLAN_STAGES = new Set(["C2", "C4", "C5"]);
const PROCESSING_STAGES = new Set(["C1", "C2", "C3", "C4", "C5", "C6"]);
function planObject(value: unknown, code: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ReportContractError(`${code}_invalid`);
  return value as Record<string, unknown>;
}

function planText(value: unknown, code: string, max = 2_000): string {
  if (typeof value !== "string" || !value.trim() || value.length > max)
    throw new ReportContractError(`${code}_invalid`);
  return value;
}

function planInteger(
  value: unknown,
  code: string,
  min: number,
  max: number,
): number {
  if (
    !Number.isInteger(value) ||
    (value as number) < min ||
    (value as number) > max
  )
    throw new ReportContractError(`${code}_invalid`);
  return value as number;
}

export function parseProcessingPlan(
  value: unknown,
  recordingId: string,
): ProcessingPlan {
  const plan = planObject(value, "plan");
  const expectedKeys = [
    "id",
    "recording_id",
    "plan_fingerprint",
    "privacy_revision",
    "accepted",
    "state",
    "cost_label",
    "max_cost_paise",
    "automatic_c5_repair_cost_paise",
    "max_entitlement_seconds",
    "expires_at_epoch",
    "stages",
    "current_stage",
    "report_ready",
    "report_run_id",
    "automatic_progression",
    "failure_code",
    "report_language",
    "coaching_prompt_revision",
  ];
  if (Object.keys(plan).some((key) => !expectedKeys.includes(key)))
    throw new ReportContractError("plan_unknown_field");
  const id = planText(plan.id, "plan_id", 128);
  encodeConversationId(id, "plan_id");
  if (planText(plan.recording_id, "plan_recording_id", 128) !== recordingId)
    throw new ReportContractError("plan_recording_id_mismatch");
  const fingerprint = planText(plan.plan_fingerprint, "plan_fingerprint", 64);
  if (!/^[a-f0-9]{64}$/.test(fingerprint))
    throw new ReportContractError("plan_fingerprint_invalid");
  if (plan.privacy_revision !== "sales-xray-processing-plan-v1")
    throw new ReportContractError("plan_privacy_revision_invalid");
  if (typeof plan.accepted !== "boolean")
    throw new ReportContractError("plan_accepted_invalid");
  const state = planText(
    plan.state,
    "plan_state",
    32,
  ) as ProcessingPlan["state"];
  if (!PLAN_STATES.has(state))
    throw new ReportContractError("plan_state_invalid");
  const maximumCost = planInteger(
    plan.max_cost_paise,
    "plan_cost_limit",
    0,
    2_147_483_647,
  );
  const automaticRepairCost =
    plan.automatic_c5_repair_cost_paise === undefined
      ? 0
      : planInteger(
          plan.automatic_c5_repair_cost_paise,
          "plan_repair_cost_limit",
          0,
          2_147_483_647,
        );
  const costLabel =
    maximumCost === 0
      ? "₹0 · approved allowance"
      : `Up to ₹${Math.floor(maximumCost / 100)}.${String(maximumCost % 100).padStart(2, "0")} · approved budget`;
  if (plan.cost_label !== costLabel)
    throw new ReportContractError("plan_cost_invalid");
  const maxEntitlement = planInteger(
    plan.max_entitlement_seconds,
    "plan_entitlement",
    0,
    86_400,
  );
  const expires = planInteger(
    plan.expires_at_epoch,
    "plan_expiry",
    1,
    4_102_444_800,
  );
  if (!Array.isArray(plan.stages) || plan.stages.length !== 3)
    throw new ReportContractError("plan_stages_invalid");
  const stages = plan.stages.map((value, index) => {
    const stage = planObject(value, `plan_stage_${index}`);
    const keys = [
      "stage",
      "provider",
      "model",
      "max_requests",
      "privacy_revision",
      "privacy_notice",
    ];
    if (Object.keys(stage).some((key) => !keys.includes(key)))
      throw new ReportContractError(`plan_stage_${index}_unknown_field`);
    const name = planText(
      stage.stage,
      `plan_stage_${index}_name`,
      8,
    ) as ProcessingPlanStage["stage"];
    if (!PLAN_STAGES.has(name))
      throw new ReportContractError(`plan_stage_${index}_name_invalid`);
    return {
      stage: name,
      provider: planText(stage.provider, `plan_stage_${index}_provider`, 128),
      model: planText(stage.model, `plan_stage_${index}_model`, 256),
      max_requests: planInteger(
        stage.max_requests,
        `plan_stage_${index}_requests`,
        1,
        64,
      ),
      privacy_revision: planText(
        stage.privacy_revision,
        `plan_stage_${index}_privacy`,
        128,
      ),
      privacy_notice: planText(
        stage.privacy_notice,
        `plan_stage_${index}_notice`,
        2_000,
      ),
    };
  });
  if (new Set(stages.map((stage) => stage.stage)).size !== stages.length)
    throw new ReportContractError("plan_stages_duplicate");
  const current =
    plan.current_stage === null
      ? null
      : planText(plan.current_stage, "plan_current_stage", 8);
  if (current !== null && !PROCESSING_STAGES.has(current))
    throw new ReportContractError("plan_current_stage_invalid");
  const reportRunId =
    plan.report_run_id === null
      ? null
      : planText(plan.report_run_id, "plan_report_run_id", 128);
  if (reportRunId !== null)
    encodeConversationId(reportRunId, "plan_report_run_id");
  if (
    typeof plan.report_ready !== "boolean" ||
    plan.automatic_progression !== true
  )
    throw new ReportContractError("plan_progress_invalid");
  const failure =
    plan.failure_code === null
      ? null
      : planText(plan.failure_code, "plan_failure_code", 128);
  const languageOptions: Pick<
    ProcessingPlan,
    "report_language" | "coaching_prompt_revision"
  > = {};
  if (
    plan.report_language !== undefined ||
    plan.coaching_prompt_revision !== undefined
  ) {
    languageOptions.report_language = parseReportLanguage(plan.report_language);
    if (
      ![
        "coaching-v1",
        "coaching-v2",
        "coaching-v3",
        "coaching-v4",
        "coaching-v5",
      ].includes(String(plan.coaching_prompt_revision)) ||
      (!["coaching-v4", "coaching-v5"].includes(
        String(plan.coaching_prompt_revision),
      ) &&
        languageOptions.report_language !== "en")
    )
      throw new ReportContractError("plan_language_revision_invalid");
    languageOptions.coaching_prompt_revision =
      plan.coaching_prompt_revision as ProcessingPlan["coaching_prompt_revision"];
  }
  return {
    ...languageOptions,
    id,
    recording_id: recordingId,
    plan_fingerprint: fingerprint,
    privacy_revision: "sales-xray-processing-plan-v1",
    accepted: plan.accepted,
    state,
    cost_label: costLabel,
    max_cost_paise: maximumCost,
    automatic_c5_repair_cost_paise: automaticRepairCost,
    max_entitlement_seconds: maxEntitlement,
    expires_at_epoch: expires,
    stages,
    current_stage: current,
    report_ready: plan.report_ready,
    report_run_id: reportRunId,
    automatic_progression: true,
    failure_code: failure,
  };
}
