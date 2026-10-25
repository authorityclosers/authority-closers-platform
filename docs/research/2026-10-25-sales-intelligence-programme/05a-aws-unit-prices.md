# AWS migration cost research: Sales X-Ray (verified unit prices)

**Date seen:** 25 Oct 2026 (all rows unless stated otherwise). **Region:** ap-south-1 Mumbai; ap-south-2 Hyderabad where relevant. **Currency:** USD list prices, without tax. A "month" means 730 hours.

**How prices were collected.** AWS prices come straight from AWS's public machine-readable price files, not from blogs:
- The bulk Price List API (`https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<Service>/current/ap-south-1/index.json|csv`). The publication date of each file is noted.
- The Savings Plans price files (`.../savingsPlan/v1.0/aws/AWSComputeSavingsPlan/...` and `AWSDatabaseSavingsPlans/...`).
- The EC2 metered-unit map (`https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Asia Pacific (Mumbai)/Linux/index.json`, published 2026-10-23).
- The EC2 Spot price feed (`https://website.spot.ec2.aws.a2z.com/spot.js`) and Spot Advisor data (`https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json`).

"Not verified" or "assumed" marks anything that could not be confirmed. The web-search quota ran out partway through, so some secondary facts were fetched only from known first-party URLs.

---

## 0. Baseline today: Hostinger KVM 4

| Item | Value | Source |
|---|---|---|
| Specs | 4 vCPU, 16 GB RAM, 200 GB NVMe, 16 TB bandwidth | https://www.hostinger.com/in/vps-hosting |
| India price | ₹1,099/mo promotional; **₹2,399/mo renewal** ("renews … for 2 years"), all plans paid upfront | same |
| USD price | $12.99/mo promotional; $28.99/mo renewal | https://www.hostinger.com/vps-hosting |
| ₹2,399 in USD | ≈ $25.27/mo at ₹94.94 | computed |
| GST | Not stated on the page. 18% GST on top is **assumed**. | — |
| Location | Hostinger lists a Mumbai VPS data centre. Our account's actual DC was not verified in this pass. Project records name "Hostinger International Limited (India)" as processor. | Hostinger support / project memory |
| Operational note | On 7–8 Oct 2026 Hostinger auto-throttled our VPS to a 40% CPU cap after sustained high CPU. The threshold is not published. Prod, staging and dev all share this one host. | project memory `project-vps-cpu-steal-20261008` |

---

## 1. EC2 compute (Linux, shared tenancy)

On-demand (OD) prices from the metered map, published 2026-10-23. Savings Plan (SP) prices from the Compute SP file, published 2026-10-23. All SP prices are 1-year, No Upfront.

| Instance | vCPU / RAM | OD $/h | OD $/mo | Compute SP $/h (saving) | EC2 Instance SP $/h (saving) | Spot $/h now (saving vs OD) |
|---|---|---|---|---|---|---|
| t4g.medium | 2 / 4 GiB | 0.0224 | 16.35 | 0.0162 (−27.7%) | 0.0142 (−36.6%) | 0.0078 (−65%) |
| t4g.large | 2 / 8 GiB | 0.0448 | 32.70 | 0.0324 (−27.7%) | 0.0283 (−36.8%) | 0.0205 (−54%) |
| t4g.xlarge | 4 / 16 GiB | 0.0896 | 65.41 | 0.0648 (−27.7%) | 0.0567 (−36.7%) | 0.0400 (−55%) |
| m7g.large | 2 / 8 GiB | 0.0583 | 42.56 | 0.0430 (−26.2%) | 0.0385 (−34.0%) | 0.0202 (−65%) |
| m7g.xlarge | 4 / 16 GiB | 0.1166 | 85.12 | 0.0861 (−26.2%) | 0.0770 (−34.0%) | 0.0561 (−52%) |
| c7g.large | 2 / 4 GiB | 0.0491 | 35.84 | 0.0374 (−23.8%) | 0.0325 (−33.8%) | 0.0258 (−47%) |
| c7g.xlarge | 4 / 8 GiB | 0.0982 | 71.69 | 0.0748 (−23.8%) | 0.0650 (−33.8%) | 0.0411 (−58%) |
| m7i.large (x86) | 2 / 8 GiB | 0.10605 | 77.42 | 0.07828 (−26.2%) | 0.07004 (−34.0%) | 0.0322 (−70%) |
| m7i.xlarge (x86) | 4 / 16 GiB | 0.2121 | 154.83 | 0.15655 (−26.2%) | 0.14007 (−34.0%) | 0.0814 (−62%) |
| m8g.large (newer Graviton) | 2 / 8 GiB | 0.0642 | 46.84 | 0.04736 | 0.04237 | — |
| c8g.large | 2 / 4 GiB | 0.0540 | 39.41 | 0.04114 | 0.03574 | — |

- **Hyderabad:** on-demand prices for every type above are **identical** to Mumbai (map published 2026-10-23). Spot is cheaper there: m7g.large $0.0137, c7g.large $0.0119.
- **Graviton vs x86:** m7g is about 45% cheaper than m7i at the same size in Mumbai.
- **Reserved Instances:** standard RIs price about the same as EC2 Instance SPs, but SPs are more flexible. RI rows were not extracted separately.
- **Spot:** the snapshot is from the live feed on 25 Oct 2026 and prices move. AWS Spot Advisor data (file last modified 20 Mar 2026, so it is stale) gives these Mumbai figures:

  | Instance | Spot saving | Interruption band |
  |---|---|---|
  | m7g.large | 45% | 15–20% |
  | m7g.xlarge | 47% | 10–15% |
  | c7g.large | 38% | >20% |
  | c7g.xlarge | 44% | 15–20% |
  | t4g.medium | 60% | >20% |

  Spot is suitable for retryable ffmpeg and AI-call worker jobs, not for Postgres or the API.

**Block storage (EC2 bulk CSV, published 2026-10-23):**

| Item | Price |
|---|---|
| EBS gp3 | $0.0912/GB-mo |
| Extra gp3 IOPS | $0.0057/IOPS-mo |
| Extra gp3 throughput | $0.0456/MiBps-mo |
| EBS snapshots | $0.05/GB-mo |

---

## 2. Databases: RDS PostgreSQL and Aurora PostgreSQL

From the RDS bulk CSV for ap-south-1, published 2026-10-20.

| Item | Single-AZ | Multi-AZ (1 standby) | 1-yr RI, No Upfront (S-AZ / M-AZ) |
|---|---|---|---|
| db.t4g.micro | $0.021/h | $0.042/h | $0.0165 / $0.033 |
| db.t4g.small | $0.042/h | $0.084/h | $0.033 / $0.066 |
| **db.t4g.medium** (2 vCPU / 4 GiB) | **$0.084/h = $61.32/mo** | **$0.167/h = $121.91/mo** | $0.066 / $0.1321 (−21%) |
| **db.t4g.large** (2 / 8 GiB) | **$0.167/h = $121.91/mo** | **$0.334/h = $243.82/mo** | $0.1321 / $0.2642 (−21%) |
| **db.m7g.large** (2 / 8 GiB) | **$0.240/h = $175.20/mo** | **$0.479/h = $349.67/mo** | $0.1844 / $0.3688 (−23%) |
| db.m7g.xlarge | $0.479/h | $0.958/h | $0.3688 / $0.7377 |
| db.m8g.large | $0.240/h | $0.480/h | $0.1608 / $0.3216 |
| gp3 storage | $0.131/GB-mo | $0.262/GB-mo | — |
| Backup storage beyond the free allowance | $0.095/GB-mo | — | — |

- **Free backup storage:** "Free backup storage is provided up to your account's total provisioned database storage across the entire region" (https://aws.amazon.com/rds/faqs/).
- **Hyderabad:** db.t4g.medium and db.t4g.large are identical to Mumbai. db.m7g.large is $0.2396 Single-AZ and $0.4792 Multi-AZ.

**Database Savings Plans** (file published 2026-10-21; https://aws.amazon.com/savingsplans/database-pricing/):
- 1-year term, No Upfront only, "up to 35%".
- In Mumbai, RDS PostgreSQL db.m7g.large is $0.192/h Single-AZ and $0.3832/h Multi-AZ, a 20% saving.
- Aurora Serverless v2 is $0.117/ACU-h, a 35% saving.
- **db.t4g is not covered.** The Mumbai file lists only db.m7g/m7i/m8a/m8g/m8i/r7g/r7i/r8g/r8i/x2m, plus serverless usage. ElastiCache Valkey serverless is also covered.

**Aurora PostgreSQL** (same CSV):

| Item | Aurora Standard | Aurora I/O-Optimized |
|---|---|---|
| Serverless v2 | **$0.18/ACU-h** (1 ACU ≈ 2 GiB; 0.5 ACU always on = $65.70/mo) | $0.24/ACU-h (+33%) |
| Storage | $0.11/GB-mo | $0.248/GB-mo (2.25×) |
| I/O | $0.22 per million requests | included |
| Backup beyond the free allowance | $0.023/GB-mo | — |
| Provisioned db.t4g.medium | $0.093/h | — |

- **When I/O-Optimized pays off:** AWS says it is "the best choice when your I/O spending is 25% or more of your total Aurora database spending."
- **Switching:** Standard → I/O-Optimized once every 30 days; back to Standard at any time (https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html).
- **Scale to zero:** Serverless v2 now scales to **0 ACU with auto-pause**. Aurora PostgreSQL needs ≥16.3 / 15.7 / 14.12 / 13.15. Resume takes about 15 s, or 30 s+ after more than 24 h paused. Auto-pause is blocked by RDS Proxy, logical replication or open connections. This makes it good for dev and staging, not for prod (https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html).

---

## 3. Object storage, egress and CDN

Sources: S3 bulk file (published 2026-10-15), AWSDataTransfer (2026-09-16), CloudFront (2026-10-19).

| Item | Mumbai price |
|---|---|
| S3 Standard | **$0.025/GB-mo** (first 50 TB), $0.024 next 450 TB, $0.023 above (Hyderabad identical) |
| S3 Standard-IA | $0.0138/GB-mo; retrieval $0.01/GB; PUT $0.01 per 1k; GET $0.001 per 1k |
| S3 One Zone-IA | $0.011/GB-mo |
| S3 Intelligent-Tiering | Frequent $0.025, Infrequent $0.0138, Archive Instant $0.005/GB-mo; monitoring $0.0025 per 1,000 objects/mo |
| S3 Glacier Instant Retrieval | $0.005/GB-mo; retrieval $0.03/GB; PUT $0.02 per 1k |
| S3 requests (Standard) | PUT/COPY/POST/LIST **$0.005 per 1,000** ($5.00/M); GET **$0.0004 per 1,000** ($0.40/M) |
| Data transfer out to internet | **First 100 GB/mo free (aggregated across all regions)**, then **$0.1093/GB** for the first 10 TB, $0.085 next 40 TB, $0.082 next 100 TB, $0.080 above 150 TB |
| Inter-AZ transfer | $0.01/GB in each direction (matters for Multi-AZ and cross-AZ traffic) |
| Mumbai → Hyderabad (cross-region DR copy) | $0.086/GB |
| CloudFront, India edge (pay as you go) | **$0.109/GB** first 10 TB, $0.085 next 40 TB, $0.082 next 100 TB; HTTPS $0.0120 per 10k requests; free tier 1 TB and 10M requests/mo |
| CloudFront flat-rate plans | Free $0 (100 GB, 1M requests); **Pro $15/mo** (50 TB, 10M requests, WAF, Route 53 DNS); Business $200/mo (https://aws.amazon.com/cloudfront/pricing/) |

**Cloudflare R2 compared** (https://developers.cloudflare.com/r2/pricing/):

| R2 item | Standard | Infrequent Access |
|---|---|---|
| Storage | **$0.015/GB-mo** | $0.01/GB-mo |
| Retrieval | none | $0.01/GB |
| Class A operations | **$4.50/M** | $9.00/M |
| Class B operations | **$0.36/M** | $0.90/M |
| Egress | **free** | free |
| Free tier (Standard only) | 10 GB-mo, 1M Class A, 10M Class B | — |

- **Worked example, 1 TB stored:** S3 Standard is about $25.6/mo and R2 about $15.2/mo. Serving 1 TB/mo to the internet adds about $101 on S3 directly or about $0 on R2.
- **Residency:** R2 has **no India location or jurisdiction**. Jurisdictions are eu, fedramp and us. Location hints such as `apac` are "a best effort and not a guarantee" (https://developers.cloudflare.com/r2/reference/data-location/). S3 Mumbai/Hyderabad gives guaranteed in-country storage.

---

## 4. Containers and serverless compute

| Item | Mumbai price | Source / date |
|---|---|---|
| **Fargate ARM (Graviton)** | **$0.02383/vCPU-h + $0.00261/GB-h** (Hyderabad identical) | ECS bulk file 2026-10-19 |
| Fargate x86 | $0.04256/vCPU-h + $0.004655/GB-h | same |
| Fargate ARM, Compute SP 1-yr No Upfront | $0.018774/vCPU-h + $0.002058/GB-h (−21%) | Compute SP file 2026-10-23 |
| Fargate ephemeral storage | $0.000127/GB-h (free base allowance not re-verified) | ECS bulk |
| Example: one ARM task with 1 vCPU / 2 GB running 24×7 | $21.21/mo OD; $16.71 with SP (x86: $37.87) | computed |
| Example: 4 vCPU / 16 GB of ARM Fargate | $100.07/mo OD | computed |
| Fargate Spot | Not verified (dynamic pricing; historically x86 only) | — |
| **App Runner** | $0.068096/vCPU-h + $0.007448/GB-h, but **closed to new customers**; AWS recommends **ECS Express Mode** (Fargate + ALB + autoscaling, no extra charge) | https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html |
| Lambda ARM | **$0.0000133334/GB-s** (first 7.5B GB-s/mo); requests $0.20/M; free 400,000 GB-s and 1M requests/mo | Lambda bulk 2026-10-22 |

---

## 5. Networking, observability, cache and queue

| Item | Mumbai price | Note |
|---|---|---|
| **Application Load Balancer** | **$0.0239/h ($17.45/mo) + $0.008/LCU-h** | ELB bulk 2026-09-11. NLB is $0.0239/h + $0.006/LCU-h |
| **NAT Gateway** | **$0.056/h ($40.88/mo per AZ) + $0.056/GB processed** | EC2 CSV 2026-10-23. This is the cost trap: workers pulling recordings or AI API traffic through NAT pay $0.056/GB on top of egress. Use public subnets with security groups, or the S3 gateway endpoint (free; not re-verified in this pass). |
| VPC interface endpoint | $0.013/h per AZ | VPC bulk 2026-10-16 |
| **Public IPv4** | **$0.005/h per address, in use or idle ($3.65/mo)** | Since 1 Feb 2024 (https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/). An ALB across 2 AZs uses at least 2. |
| **CloudWatch Logs** | **$0.67/GB ingested** (Standard class); $0.03/GB-mo stored; Logs Insights $0.0067/GB scanned; 5 GB free | CW bulk 2026-10-07. Verbose app logs are a silent cost. |
| CloudWatch custom metrics | $0.30/metric-mo (first 10k) | same |
| ElastiCache Valkey nodes | cache.t4g.micro **$0.016/h ($11.68/mo)**; t4g.small $0.0328/h ($23.94); t4g.medium $0.0648/h ($47.30); m7g.large $0.1312/h | ElastiCache bulk 2026-10-14. Redis OSS on the same node costs about 25% more. |
| ElastiCache Serverless Valkey | $0.054 per GB-hour stored; $0.0015 per million ECPUs | same |
| **SQS** | Standard **$0.40/M requests** (first 1M/mo free); FIFO $0.50/M | SQS bulk 2026-09-11 |

---

## 6. Credits and free tier

| Programme | Facts | Source |
|---|---|---|
| AWS Activate Founders (self-funded) | "Up to $5,000"; starts at $1,000; select participants get more | https://aws.amazon.com/startups/credits |
| AWS Activate Portfolio | "Up to $200,000"; needs an Org ID from an Activate Provider (VC, accelerator, angel) | same |
| Activate eligibility | Pre-Series B, founded in the last 10 years, AWS account on the **Paid** plan, new to Activate or asking for more than received before | same |
| Credit exclusions | Not usable for: **upfront fees of Savings Plans/RIs**, Marketplace, Professional Services, some Support tiers, Route 53 domains, mining. Expiry is set per code. | https://aws.amazon.com/awscredits/ |
| New Free Tier (since **15 Jul 2025**) | $100 credit at sign-up, plus up to $100 more for 5 starter activities ($20 each). The Free plan lasts 6 months or until credits run out, then the account closes unless upgraded to Paid. Some services are blocked on the Free plan. Accounts opened before 15 Jul 2025 keep the legacy 12-month tier. Paid-plan sign-ups also get up to $200. | https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits/ and https://aws.amazon.com/free/ |
| India-specific AWS programmes | **Not verified.** The India startups page returned 404 and the search quota ran out. | — |

---

## 7. Currency and tax

| Item | Value | Source |
|---|---|---|
| USD→INR | **94.94** (ECB reference, 23 Oct 2026); 95.04 (ExchangeRate-API, 24 Oct 2026). Use **₹95** for planning. | https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR ; https://open.er-api.com/v6/latest/USD |
| AWS India billing | Accounts with an India billing address contract with **Amazon Web Services India Private Limited (AWS India; legacy name AISPL)**, and "your invoice total is listed in rupees instead of dollars". Legacy accounts are being moved to a new seller-of-record model by Dec 2026. | https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/manage-account-payment-aispl.html |
| GST | **18%**: IGST for customers outside Delhi, or CGST 9% + SGST 9% in Delhi. Adding a GSTIN in Tax Settings allows input-tax credit "in accordance with local law". | https://aws.amazon.com/tax-help/india/ |
| Effect | With a GSTIN, the 18% is recoverable, so the effective cost is about the USD list price × FX rate. Without a GSTIN, multiply by 1.18. | derived |

---

## 8. SaaS cost benchmarks and pay-as-you-grow patterns

| Reference | Figure | Source |
|---|---|---|
| Public cloud-software median gross margin | **76%** (so COGS ≈ 24% of revenue); median FCF margin 21% (Clouded Judgement, 23 Oct 2026) | https://cloudedjudgement.substack.com/p/clouded-judgement-102226-ai-goes |
| Private SaaS hosting spend | Median **hosting = 5% of ARR**; pro-services COGS 5%; other COGS 3%; DevOps 4% (SaaS Capital, survey Mar 2026, >1,000 companies, published 10 Jun 2026) | https://www.saas-capital.com/blog-posts/spending-benchmarks-for-private-b2b-saas-companies/ |
| Cloud as share of cost of revenue | Committed cloud spend averages about **50% of cost of revenue** at public software companies; 75–80% is "common" in some. Committed-use discounts cut compute about 30–50% (a16z, May 2021) | https://a16z.com/the-cost-of-cloud-a-trillion-dollar-paradox/ |
| AI-heavy products | AI "Shooting Stars" average about **60%** gross margin; "Supernovas" about **25%** (BVP, Aug 2025). This matters because our AI API bill is COGS, not hosting. | https://www.bvp.com/atlas/the-state-of-ai-2025 |
| KeyBanc / ICONIQ | **Not verified.** The ICONIQ 2025 State of AI page has no margin figures in text, and KeyBanc was not reachable. | — |

**Pay-as-you-grow levers (measured in Mumbai):**
- **Compute Savings Plans:** up to 72% off on 3-year terms (https://docs.aws.amazon.com/savingsplans/latest/userguide/what-is-savings-plans.html). For 1-year No Upfront on Graviton in Mumbai the measured saving is 24–28%, and 34–37% with an EC2 Instance SP. They also cover Fargate (−21%) and Lambda.
- **Database Savings Plans:** 1-year, about 20% on RDS m7g/m8g and 35% on Aurora Serverless v2. They do not cover t4g.
- **Spot:** 47–70% off on worker types at today's snapshot.
- **Aurora Serverless v2 at 0 ACU:** dev and staging databases pay only for storage while idle.
- **ECS Express Mode:** Fargate with autoscaling, no service fee.
- **Credits:** they cannot pay SP/RI upfront fees, so commit with No Upfront plans while on credits.

---

## 9. Alternatives (one line each)

| Provider | India region? | Comparable price (date seen 25 Oct 2026) | Source |
|---|---|---|---|
| Hetzner | **No.** Germany, Finland, Singapore, USA. | CPX32 (4 vCPU/8 GB) €35.99/mo EU or €49.49 Singapore; CPX42 (8/16) €69.99 EU or €93.99 SIN. IPv4 included; ex-VAT; create buttons showed "currently unavailable". | https://www.hetzner.com/cloud/regular-performance/ |
| DigitalOcean | Yes, Bangalore | Basic 4 vCPU/8 GiB $48/mo (5 TB transfer); General Purpose 4/16 GiB $126/mo. Regional price variation not stated. | https://www.digitalocean.com/pricing/droplets |
| Google Cloud | Yes, Mumbai (asia-south1) and Delhi (asia-south2) | e2-standard-4 (4/16): $0.161/h = $117.51/mo, 1-yr CUD $74.03/mo, Spot $0.0966/h Mumbai and $0.0791 Delhi. **T2A Arm not offered in India.** c4a-standard-4 (Axion Arm) Mumbai $136.35/mo, CUD $89.92. | https://gcloud-compute.com/e2-standard-4.html , /c4a-standard-4.html (third-party, data updated 18 Oct 2026) |
| Azure | Yes, Central India | D4ps_v5 (4/16 Arm) $0.101/h ≈ $73.73/mo; B4ps_v2 (burstable 4/16 Arm) $0.0896/h ≈ $65.41; D2ps_v5 $0.0506/h | Azure Retail Prices API (https://prices.azure.com/api/retail/prices, centralindia) |
| E2E Networks (Indian provider) | Yes (Indian; specific DCs not shown on the page) | C3.8GB (4 vCPU/8 GB) $0.049/h = $35.64/mo; C3.16GB (8/16) $70.13/mo. Object storage $10 flat up to 250 GB, then $0.0375/GB; ex-GST. The page showed USD; INR prices not verified. | https://www.e2enetworks.com/pricing |

---

## 10. Illustrative arithmetic (sizes assumed, not a quote)

| Stack (Mumbai, on-demand, 730 h) | Monthly |
|---|---|
| **A. Lift-and-shift one box:** t4g.xlarge ($65.41) + 200 GB gp3 ($18.24) + 1 IPv4 ($3.65) + 50 GB snapshots ($2.50) | **≈ $90 (₹8.5k)**; ≈ $72 with a 1-yr Compute SP. Compare KVM 4 at ₹2,399 (≈ $25). |
| **B. Managed minimum (prod only):** Fargate ARM, 5 tasks of 0.5–1 vCPU ($63.6), ALB plus about 1 LCU ($23.3), RDS db.t4g.medium Single-AZ with 50 GB ($67.9), S3 100 GB ($2.5), 10 GB logs ($6.7), 2 IPv4 ($7.3) | **≈ $171 (₹16k)**. Add ≈ $41 if a NAT Gateway is used, and ≈ $67 for Multi-AZ RDS. |

AI transcription and analysis costs are billed by the AI provider and are excluded from both.

DPDP Act 2023 is background only and was not re-verified in this pass. The Act restricts cross-border transfers only to countries the government notifies (a negative list); it has no blanket localisation rule. Mumbai plus Hyderabad would give in-country primary storage and disaster recovery (DR). R2 and the Google Drive backups cannot guarantee India-only storage.
