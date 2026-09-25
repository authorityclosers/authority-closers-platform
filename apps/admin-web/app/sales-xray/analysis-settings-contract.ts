import { z } from "zod";

export const coachingRevisionSchema = z.enum([
  "coaching-v3",
  "coaching-v4",
  "coaching-v5",
]);

export const settingsSchema = z
  .object({
    c4_max_requests: z.number().int().min(1).max(64),
    c4_max_completion_tokens: z.number().int().min(256).max(4000),
    c5_max_completion_tokens: z.number().int().min(256).max(8000),
    c5_output_profile: z.enum(["standard", "detailed"]),
    c5_coaching_prompt_revision: coachingRevisionSchema.default("coaching-v3"),
    report_language_default: z
      .enum(["en", "hi-Deva+en", "mr-Deva+en"])
      .default("en"),
  })
  .strict()
  .refine(
    (value) =>
      value.c5_coaching_prompt_revision !== "coaching-v3" ||
      value.report_language_default === "en",
    {
      message: "Hindi and Marathi reports require the qualitative v0.2 engine.",
      path: ["report_language_default"],
    },
  );

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
        c5_coaching_prompt_revision: z
          .object({
            values: z.array(coachingRevisionSchema),
          })
          .default({ values: ["coaching-v3"] }),
        report_language_default: z
          .object({
            values: z.array(z.enum(["en", "hi-Deva+en", "mr-Deva+en"])),
          })
          .default({ values: ["en"] }),
      })
      .strict(),
    created_at: z.string().nullable(),
    message: z.string().min(1),
  })
  .strict();
