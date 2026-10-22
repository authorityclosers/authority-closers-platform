# P1 is built: Brain 4.0 inside the production one-pass read (recipe one-pass-facts-v2), 22 Oct 2026

From the one-pass session, for the orchestrator and the cost research session. **The Brain 4.0 part is written:
don't write `one_pass/brain4_part.py` again.** Orchestrator, 22 Oct 2026: "Yes, build both the part and the
wiring."

## What landed (workbench)
- **`one_pass/brain4_part.py`**
  - The v2 prompt is v1's own stage prompt with the header naming four parts, then `brain4.part_instructions()`. It
    is built from v1's text, so the two cannot drift.
  - The v2 schema is v1's plus a required `brain4` part (`brain4.response_schema()`).
  - `parse()` checks the block with `brain4.parse` against the segments that are not withheld, and never raises.
- **`one_pass/markers.py`**: `RECIPE_V2` (`one-pass-facts-v2`), `PROMPT_REVISION_V2` (`one-pass-v2`), `MARKER_V2`,
  and `recipe_of()`.
- **Routing.**
  - `stage`, the Gemini and OpenAI adapters, the completion ceiling, the broker, the processing plan, the reporting
    pipeline and the Admin one-pass checks all carry the recipe.
  - Each recipe goes only with its own schema (OpenAI format `sales_xray_one_pass_facts_v2`).
- **`plan_publish`**
  - A v2 read publishes its parsed Brain 4.0 block inside the pointer review. The Report already prefers a review's
    own block, and `brain4_shadow` skips that call.
  - A block that does not parse is left out (`brain4: unusable:<code>`), and the review is always kept.
- **Seal and switch.**
  - `c2_route` takes `recipe=`. v2 has its own configuration revision and profiles: `gemini-one-pass-v2[-flex]` and
    `luna-c4-one-pass-v2[-flex]`.
  - Seal: `scripts/ops/one_pass_c2_seal.py --one-pass --brain4`.
  - Switch: `scripts/data-changes/one-pass-flex-production.py --one-pass --brain4`. Prepare and switch need the
    owner's words in `--reason`.

## v1 is byte-identical
- Checked on the workbench, old code against new:
  - the v1 system prompt and schema;
  - the Gemini and Luna request bodies, standard and Flex;
  - every derived configuration digest: plain, one-pass and hybrid, standard and Flex;
  - every seal digest on one fixed bundle.
- Production's sealed v1 profiles are untouched.

## Next
1. **Dev trial: done** (`04-p1-brain4-trial.md`). On 8 AC calls on standard (Flex was refusing):
   - every contract passed and every Brain 4.0 block parsed;
   - ₹0.40 per audio minute for C4, about ₹1 a call more than v1;
   - calibration v1 keeps the review within its own band, so no refit.
2. **Recommendation:** switch to v2 when Brain 4.0 becomes the Report. Until then it adds about ₹1 a call for
   workspaces that don't show Brain 4.0.
3. **Root seals v2** when that is decided, after the Luna option C chain; then the owner's words, and the switch.

Handover note with commands: the shared notes folder, `p1-brain4-one-pass-v2-20261022.md`.
