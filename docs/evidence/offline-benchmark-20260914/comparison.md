# Sales Xray offline comparison

These results test fixture-authored context and profile rules. They do not measure model quality, sales skill, human review agreement or hosted processing speed.

Run: `c4ec2492-7828-4d9f-b8d5-e5f8c6d4d962`. Result: **passed**.

8 selected cases; 16 comparisons. Provider calls: 0. ASR calls: 0. Provider spend: ₹0.

| Candidate | Passed | Failed | Local comparison p50 | Local comparison p95 |
| --- | ---: | ---: | ---: | ---: |
| source-profile-full | 8 | 0 | 6.249 ms | 7.070 ms |
| wording-fixture-bounded | 8 | 0 | 5.744 ms | 16.355 ms |

All candidates see the same retained transcript and context per case. Context preparation time is recorded separately in the JSON receipt. Each percentile includes all selected cases, including rejections; it is a nearest-rank local diagnostic, not a production latency promise.

## Cases that need attention

None failed the declared fixture expectations.

Holdout input is not opened. No profile, label or deployment is promoted. The source weight discrepancy remains 95 actual / 100 declared and numerical sales-score publication stays withheld.
