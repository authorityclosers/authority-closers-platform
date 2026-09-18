# Deepgram timing-order recovery

2026-09-16: production 20:53 call had a provider-returned response with one backward word ordering (344.81s followed by343.77002s). Individual timestamps were otherwise valid; the strict monotonic check rejected the entire C2 stage.

The derived transcript now stable-sorts validated words by start/end. Raw response bytes, hash, speaker labels and individual word timing remain unchanged. Negative, nonfinite, end-before-start and out-of-duration values remain invalid. Existing stored responses are not rewritten.

Validation: 85 focused provider/inference/worker/processing-plan tests passed, Ruff format/check passed, provider module mypy passed. Synthetic regression covers the observed backstep shape, two speakers, overlap, raw immutability and invalid timestamp boundaries. No production success or retained-C2 replay is claimed by this change.
