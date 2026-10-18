/**
 * Admin → Call data (GET /v1/admin/call-data): settings revision, model menu,
 * today's spend and recent runs. Normalizers give every field a default; the
 * settings go back to the API in its own snake_case shape. Pure.
 */
import { read } from "../lib/read";

export type PipelineConfig = {
  enabled: boolean;
  model: string;
  dailyCapInr: number;
  maxCallMinutes: number;
};

export type StreamingConfig = {
  provider: string;
  model: string;
  language: string;
  mode: string;
};

export type StreamingProvider = {
  key: string;
  label: string;
  status: string;
  models: string[];
  inrPerHour: string;
  note: string;
  gateCleared: boolean;
};

export type CallDataSettings = {
  revision: number | null;
  config: {
    fast: PipelineConfig;
    deep: PipelineConfig;
    streaming: StreamingConfig;
  };
  streaming: {
    providers: StreamingProvider[];
    languages: string[];
    modes: string[];
  };
  models: {
    model: string;
    label: string;
    inputUsd: string;
    outputUsd: string;
  }[];
  spentToday: { fast: number; deep: number };
  recent: {
    recordingId: string;
    pipeline: string;
    state: string;
    reason: string | null;
    model: string | null;
    costInr: number | null;
    durationMs: number | null;
    facts: number | null;
    workspace: string;
    at: string;
  }[];
};

function pipeline(raw: unknown): PipelineConfig {
  const value = read.object(raw);
  return {
    enabled: read.boolean(value.enabled),
    model: read.string(value.model, "gemini-3.8-flash"),
    dailyCapInr: read.number(value.daily_cap_inr, 0),
    maxCallMinutes: read.number(value.max_call_minutes, 60),
  };
}

export function normalizeCallData(raw: unknown): CallDataSettings {
  const body = read.object(raw);
  const config = read.object(body.config);
  const spent = read.object(body.spent_today_inr);
  const live = read.object(config.streaming);
  const menu = read.object(body.streaming);
  const gate = read.object(menu.gate);
  return {
    revision: read.optionalNumber(body.revision),
    config: {
      fast: pipeline(config.fast),
      deep: pipeline(config.deep),
      streaming: {
        provider: read.string(live.provider, "off"),
        model: read.string(live.model, "saaras:v3-realtime"),
        language: read.string(live.language, "auto"),
        mode: read.string(live.mode, "codemix"),
      },
    },
    streaming: {
      providers: read.array(menu.providers).map((item) => {
        const provider = read.object(item);
        const key = read.string(provider.key);
        return {
          key,
          label: read.string(provider.label, key),
          status: read.string(provider.status, "planned"),
          models: read.strings(provider.models),
          inrPerHour: read.string(provider.inr_per_hour),
          note: read.string(provider.note),
          gateCleared: read.boolean(gate[key]),
        };
      }),
      languages: read.strings(menu.languages),
      modes: read.strings(menu.modes),
    },
    models: read.array(body.models).map((item) => {
      const model = read.object(item);
      return {
        model: read.string(model.model),
        label: read.string(model.label, read.string(model.model)),
        inputUsd: read.string(model.input_usd_per_million),
        outputUsd: read.string(model.output_usd_per_million),
      };
    }),
    spentToday: {
      fast: read.number(spent.fast),
      deep: read.number(spent.deep),
    },
    recent: read.array(body.recent).map((item) => {
      const run = read.object(item);
      return {
        recordingId: read.string(run.recording_id),
        pipeline: read.string(run.pipeline),
        state: read.string(run.state),
        reason: read.optionalString(run.reason),
        model: read.optionalString(run.model),
        costInr: read.optionalNumber(run.cost_inr),
        durationMs: read.optionalNumber(run.duration_ms),
        facts: read.optionalNumber(run.facts),
        workspace: read.string(run.workspace),
        at: read.string(run.at),
      };
    }),
  };
}

/** The settings document the API accepts. */
export function toApi(
  config: CallDataSettings["config"],
): Record<string, unknown> {
  const one = (value: PipelineConfig) => ({
    enabled: value.enabled,
    model: value.model,
    daily_cap_inr: Math.round(value.dailyCapInr),
    max_call_minutes: Math.round(value.maxCallMinutes),
  });
  return {
    fast: one(config.fast),
    deep: one(config.deep),
    streaming: config.streaming,
  };
}
