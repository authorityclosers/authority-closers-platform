import { z } from "zod";

export const settingsSchema = z
  .object({
    c4_max_requests: z.number().int().min(1).max(64),
    c4_max_completion_tokens: z.number().int().min(256).max(4000),
    c5_max_completion_tokens: z.number().int().min(256).max(8000),
    c5_output_profile: z.enum(["standard", "detailed"]),
  })
  .strict();

export const responseSchema = z
  .object({
    revision: z.number().int().nonnegative(),
    settings: settingsSchema,
    bounds: z
      .object({
        c4_max_requests: z.object({
          min: z.number().int(),
          max: z.number().int(),
        }),
        c4_max_completion_tokens: z.object({
          min: z.number().int(),
          max: z.number().int(),
        }),
        c5_max_completion_tokens: z.object({
          min: z.number().int(),
          max: z.number().int(),
        }),
        c5_output_profile: z.object({
          values: z.array(z.enum(["standard", "detailed"])),
        }),
      })
      .strict(),
    created_at: z.string().nullable(),
    message: z.string().min(1),
  })
  .strict();
