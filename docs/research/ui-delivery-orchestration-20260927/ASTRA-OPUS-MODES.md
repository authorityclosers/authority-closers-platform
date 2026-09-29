# Astra and Opus modes for selected-reference UI delivery

Research date: 27 September 2026. This addendum supersedes the earlier medium-first role table for the **initial quality-calibration screen**. It does not change runtime settings or establish a measured winning model. The earlier research remains historical evidence.

## Decision

For the first demanding Sales Xray screen family, test **GPT-6 Astra at `xhigh` for the screen contract and independent visual/behavior review, and Claude Opus 5.5 at `xhigh` as the sole implementation writer**. Keep automatic swarm modes off. Use the selected Drive desktop/mobile pair, not regenerated images. Compare Opus `high` against `xhigh` before adopting the latter for all subsequent screens. Both models remain candidates for the writer; no published result found here proves Opus beats Astra on this library.

This is a quality-first calibration policy chosen for the owner's demanding fidelity target. It differs from vendor default recommendations. A successful first result is not an efficiency benchmark. `max` is a bounded escalation for a specific unresolved reasoning defect, not a default for every tool call.

The completed Pro follow-up recommends **high as the general baseline**, with xhigh trials on dense screens. This addendum deliberately starts the first complex report/player candidate at xhigh while retaining high as the comparison. These are different starting policies, not conflicting evidence; the comparison must determine whether extra effort earns its place. Review dispositions are in [MODE-REVIEW.md](MODE-REVIEW.md).

## Controls that must not be conflated

| Control | What it changes | Proposed use |
|---|---|---|
| Codex `gpt-6-astra` with `high` / `xhigh` / `max` | Model reasoning effort | `xhigh` for initial screen architecture and critical review; test `high` on established patterns. |
| Codex Ultra | Automatic delegation in addition to deeper work | Off for the initial screen experiment. Evaluate later only for genuinely separable tasks. |
| OpenAI Responses API `reasoning.mode: standard` / `pro` | Separate API reasoning execution mode | Documentation context only. Do not assume it is a Codex subscription toggle or open API billing to obtain it. |
| ChatGPT Pro subscription / Pro in the research chat | Product access and the selected chat option | Does not prove this Codex session uses API pro reasoning. |
| Claude `claude-opus-5-5` with `high` / `xhigh` / `max` | Opus reasoning effort | `xhigh` quality-calibration candidate; `high` controlled comparison. |
| Claude Code Ultracode | Sends `xhigh` and adds dynamic workflow orchestration | Off for a one-writer experiment; it changes more than effort. |
| Claude Plan mode | Exploration/planning permissions and workflow | Optional bounded inspection stage, then authorized implementation. It is not a deeper reasoning level. |
| Claude Fast mode | Lower latency with separate usage-credit billing | Off under the owner's no-extra-credits constraint. |

OpenAI documents Astra's effort controls and distinguishes Max from Ultra delegation. Higher effort can increase latency and tokens. [Codex models](https://learn.chatgpt.com/docs/models), [Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra).

The API's `standard`/`pro` mode is independent of effort and pro performs additional billable model work. This research has not verified a matching Codex UI setting. [API reasoning](https://developers.openai.com/api/docs/guides/reasoning).

Claude Code supports `xhigh` and `max` on Opus 5.5. Opus 5.5 defaults to medium; Ultracode combines `xhigh` with workflow orchestration. Its Plan mode is a permission mode. [Model configuration](https://code.claude.com/docs/en/model-config), [CLI reference](https://code.claude.com/docs/en/cli-reference).

Claude Fast mode uses usage credits rather than included subscription limits. It is a speed option, not an intelligence upgrade. This is a documented reason to exclude it here. [Fast mode](https://code.claude.com/docs/en/fast-mode).

## Stage-by-stage policy

| Stage | Starting assignment | Bounded output / evidence |
|---|---|---|
| Interpret exact reference pair and resolve responsive behavior | Astra `xhigh` | One screen contract: layout, typography, shared components, breakpoints, data/actions, microstates and file ownership. Mark unknowns. |
| Implement first complex screen or major shared shell/player | Opus 5.5 `xhigh`, sole writer | Existing app implementation, desktop/mobile captures, working actions, tests and concrete remaining discrepancies. |
| Judge initial visual fidelity and interaction completeness | Fresh Astra `xhigh`, read-only | Compare actual captures to selected images; review critical interaction evidence; return location-specific defects or acceptance evidence. |
| Repeated screen using an accepted composition | Opus 5.5 `high` candidate | Same acceptance bar; retain `xhigh` if representative comparisons show fewer defects or less total rework. |
| Difficult state/recovery/audio bug | Assigned writer `xhigh`; Astra `xhigh` for independent diagnosis where useful | Reproduction, cause, minimal fix and regression. Only one agent edits the affected files. |
| Persistent hard blocker after reproducible diagnosis | Same selected model at `max`, one bounded attempt | Explicit hypothesis and success check; preserve failed attempts. No new scope or recursive agents. |
| Mechanical measurements, filenames, test-result inventory | Deterministic scripts or a bounded helper | No design authority. Do not run an additional expensive model solely to repeat tool output. |

These stage choices are project recommendations, not vendor UI benchmark results. Cross-model review may find different mistakes but is not guaranteed independent truth; source references and observed behavior remain the acceptance evidence. If Opus lacks included capacity, Astra can own the same screen packet and a fresh reviewer applies the same standard.

Keep the initial exercise at one screen family: report overview plus its required shell/player behavior. Do not give either model all 204 images. Extra-high effort does not remove the need for context selection or a clear completion boundary.

## What the evidence establishes

Anthropic reports that on SWE-bench Pro, Opus 5.5 `xhigh` gained about **1.4 score points** versus `high` at about **2.5 times its cost**; medium was about 2.5 points lower at about 70% of high's cost. These are vendor coding-benchmark observations, not UI visual-fidelity scores, this subscription's quota multipliers, or results from this repository. [Published effort comparison](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence).

That comparison used 478 filtered problems in Anthropic's harness, with two high/medium runs and one xhigh run. A per-turn cap truncated two xhigh attempts. The figures are not comparable to the public leaderboard. This limits how confidently a small score difference can be generalized.

Opus 5.5's effort scale is not equivalent to Opus 5's. Anthropic recommends explicitly calibrating it, reserving the highest efforts for demonstrated gains. It also reports that generic requests to avoid AI-looking design can merely change which default style appears. Exact visual direction and iterative inspection matter. [Opus 5.5 prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5).

OpenAI recommends Astra for demanding work and advises testing whether `xhigh` justifies its additional latency/usage. No task-matched Astra-versus-Opus or Astra high-versus-xhigh benchmark for the selected Drive library was established in this research. [Model selection](https://developers.openai.com/api/docs/guides/model-selection), [reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning).

## Configuration recipes for later authorized use

These are illustrative, not executed or installed. Verify the effective model, effort and authentication when a future session starts; environment variables, managed caps and UI selections can affect the result. Record exact model IDs and client versions in the receipt. Do not change global defaults to run one experiment.

For Codex, select **GPT-6 Astra → Extra high** in the model picker. Equivalent supported configuration keys are:

```toml
model = "gpt-6-astra"
model_reasoning_effort = "xhigh"
```

Use a per-run or dedicated profile override rather than editing unrelated account-wide settings. Review `/status` and effective configuration, including any separate Plan-mode effort override. These keys describe effort, not an instruction to enable Ultra. [Developer settings](https://learn.chatgpt.com/docs/developer-settings), [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

For Claude Code's future implementation session:

```text
claude --model claude-opus-5-5 --effort xhigh
```

For a bounded planning-only stage, add `--permission-mode plan`. The example does not grant additional tool permissions. Verify that Ultracode and Fast mode are off; verify effective subscription authentication and that paid usage credits are disabled. Preserve the existing authorized tool scope. No Claude process was launched for this research. [CLI reference](https://code.claude.com/docs/en/cli-reference).

Do not rotate effort repeatedly on every tiny action. Anthropic notes that changing the top-level API effort can invalidate prompt caching; API beta per-message behavior must not be assumed to describe every CLI version. Compare fresh, separate runs and record the client behavior rather than building an unverified optimization around it. [Opus 5.5 prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5).

## Minimal calibration without an exhaustive experiment

1. Freeze one challenging reference packet, original image hashes, source revision plus local delta, shared components, stable fixtures and acceptance rubric. It must include responsive reflow and at least one meaningful interaction, not just a static hero.
2. Prepare the contract once with Astra `xhigh`. Use the same contract in all implementation attempts. Its cost is common setup and must remain in total delivery accounting.
3. Run Opus 5.5 `high` and `xhigh` separately from the identical starting state, with no solution transfer. Alternate the order on a second comparable packet if the first comparison is inconclusive. Use included allowance only, with caps recorded before launch; no experiments have run yet.
4. Have the same Astra reviewer configuration assess anonymized candidates against the same selected-reference and behavior rubric, with a separate fresh context for each candidate. Record pre-review candidate quality as well as repairs, so feedback does not conceal initial differences. The coordinator resolves disagreements against evidence.
5. Measure accepted screens, visual defects by severity, behavior failures, repairs, active time, all agent/test overhead, observed usage and separately settled cash. Keep unavailable subscription deltas unknown; do not treat shared-account movement as exact task usage.
6. Keep `xhigh` where it materially improves acceptance or reduces total repair burden. Prefer `high` where both reliably meet the bar and xhigh adds overhead. If neither passes, inspect missing context/tools/contracts before increasing effort. Escalate one diagnosed blocker to max only when justified and record the result.
7. Calibrate Astra's reviewer/planner effort separately using the same frozen candidates, including known defects. Compare `high` and `xhigh` for missed real defects, false alarms and useful repairs; independent adjudication is required. Do not change writer model, reviewer effort and delegation together.

This small experiment is diagnostic, not a statistically established ranking. Do not require every user screen to be built twice after the delivery profile is chosen. Keep the existing requirement of one heavy local job, resource-health checks before heavy work, and an isolated browser-test profile.

Before launching, complete a run sheet with exact viewport sizes, browser/OS/font versions, fixture and clock values, animation treatment, tool permissions, equal timeout and repair-round limits, and explicit severity and acceptance thresholds. Use the same controls in both arms. Record cap/truncation events rather than quietly extending the weaker attempt. The existing pilot's two-repair-round and 90-active-minute ceilings are proposals to freeze before the run, not results already observed.

Comparing only high and xhigh does not establish the cheapest sufficient effort or the best writer. Medium and an Astra-writer arm would be required before making those broader claims; they are deliberately outside this first quality-calibration comparison.

## Visual work that no mode replaces

Give the writer the actual selected desktop and mobile images, relevant detail crops where needed, and a concise contract identifying what must be preserved. Inspect hierarchy, font metrics, margins, density, clipping, controls and motion in real browser captures. Use readable English/Marathi stress content and test the real task outcomes. A conceptual image is design evidence; a working screenshot is implementation evidence. They have different roles.

Require a short discrepancy list with evidence after each iteration. Use a fresh read-only reviewer at an agreed revision. Do not substitute a large reasoning budget for looking at the screenshot, and do not replace the chosen layout with a generic dashboard.

## Research status

Official documentation and existing research were inspected. The focused follow-up in the [existing Pro research chat](https://chatgpt.com/c/6ab8b0ab-0a80-83e9-857e-b9c4cf77f425) completed and was collected. The independent review and cloud recommendations were adjudicated in [MODE-REVIEW.md](MODE-REVIEW.md); the source register is [MODE-SOURCES.json](MODE-SOURCES.json). Account capacity, effective runtime settings, UI benchmarks and savings remain unverified. No provider API run, application implementation, model-settings change or deployment is part of this research.
