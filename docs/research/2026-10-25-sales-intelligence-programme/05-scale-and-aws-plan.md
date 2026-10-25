# 05 — Scaling plan: when and how to move Sales X-Ray to AWS, with spend tied to revenue

*Programme chapter 5 (Part C of the 25 Oct 2026 order). A plan only: **no migration now**.
Internal: prices and revenue figures here are never shown to users.*

**Labels.** **[M]** measured on our systems (dates given). **[E]** external, from a cited
price file or report (unit prices in `05a-aws-unit-prices.md`, AWS's own price files,
seen 25 Oct 2026, Mumbai `ap-south-1`). **[A]** assumed by us, to be replaced by
measurements. Planning rate ₹95 per US$ [E]; AWS India bills in rupees with 18% GST,
recoverable with a GSTIN [E].

---

## 1. The answer in five lines

1. **Don't move yet.** Hosting is a rounding error next to AI: one Hostinger KVM 4 costs
   ₹2,399 a month [E] and carries production, staging, dev and the agents; AI analysis costs
   ₹0.85 per plan minute [M, 23 Oct], so a single busy seller's AI bill is larger than the
   whole server.
2. **The real risks today are structural, not cost:** one shared box, a serial analysis
   worker, a 64 MiB backup cap, 28 GB of free disk and Hostinger's CPU throttle [M, 22 Oct
   capacity audit]. Fix those first, on cheap hardware, and make the stack portable.
3. **Move production to AWS Mumbai when any trigger in §5 fires**, the main one being net
   revenue of about **₹4 lakh a month** (where a managed AWS production costs ≤5% of it), or
   a capacity, reliability or customer trigger, whichever comes first.
4. **Spend follows revenue by rule:** hosting is held at **≤5–6% of trailing-3-month net
   revenue** (the private-SaaS median is 5% [E]); every step up in §6 is unlocked by a
   revenue band, not by enthusiasm.
5. **Per seller, infrastructure costs about ₹190 a month at 100 active sellers, falling to
   about ₹50–90 at 1,000–5,000** (§4), against net revenue per organisation seat of ₹9,722
   and per Personal plan of ₹2,059 [M, 23 Oct economics]. Recording storage, not compute,
   becomes the largest line, so audio retention and encoding are the biggest levers.

---

## 2. Where we are (measured)

| Fact | Value | Source |
|---|---|---|
| Host | One Hostinger KVM 4: 4 vCPU, 16 GB RAM, 200 GB NVMe; ₹2,399/month on renewal | [E] Hostinger, [M] 22 Oct audit |
| Shared with | staging, dev-live, Paperclip and agents, Pulse | [M] |
| Production CPU | average 0.06 cores, peak 0.71 (24 h) | [M] 22 Oct |
| Host CPU | average ≈1 core, peak 2.76; throttled to 40% by Hostinger on 7–8 Oct | [M] |
| Disk | 85% used, 28 GB free (96.8% on 20 Oct) | [M] |
| Database | 83 MB; ≈130 KB per analysed call | [M] |
| Audio | 1.65 MB per real call on average; 288 MB for 551 calls | [M] 19–22 Oct |
| Interactive load | 0.2–0.35 API requests/s per open app ⇒ 40–70 req/s at 200 users | [M] code + audit |
| Analysis | one serial provider consumer: ≈40–80 short calls/hour; an upload not started within 1 h is lost | [M] |
| Backups | 5-minute logical to R2 (64 MiB cap), hourly pg_dump to Drive, nightly restic | [M] |
| Fixed running costs | ≈₹12.7k/month (servers ₹4k incl. ea, a proposed separate production box ₹4k, tools ₹3.1k, test AI ₹1.6k) | [M/E] economics 23 Oct |
| AI cost | ₹0.85 per plan minute today; ₹0.43 on Flex; ₹0.36 projected for v2 on Flex | [M] |

---

## 3. What "AWS" would mean for us (target architecture)

Region **Mumbai (`ap-south-1`)** for production; **Hyderabad (`ap-south-2`)** for disaster
recovery. Both keep personal data in India (DPDP); Hyderabad on-demand prices equal
Mumbai's [E]. Cloudflare R2 has no India location or jurisdiction, only a best-effort
"apac" hint [E], so recordings move to S3 Mumbai.

| Piece | Choice | Why |
|---|---|---|
| API, web, worker | **ECS on Fargate, Graviton (ARM)**, autoscaled; ECS Express Mode (Fargate + ALB, no extra fee) | Pay per vCPU-hour, no servers; App Runner is closed to new customers [E] |
| Analysis worker | Fargate tasks scaled on queue depth; later EC2 **Spot** (c7g/m7g, 38–65% off) for retryable ffmpeg work | Our jobs are leased and retryable (`FOR UPDATE SKIP LOCKED`) [M] |
| Database | **RDS PostgreSQL** db.t4g.medium → db.m7g.large; Multi-AZ from phase 3; PITR on | Same engine, no code change; Aurora Serverless v2 (scales to 0) for staging only |
| Recordings | **S3 Mumbai**, Intelligent-Tiering after 30 days, replication to Hyderabad from phase 3 | In-India storage; IA is 45% cheaper than Standard [E] |
| Edge | **Keep Cloudflare** in front (free plan, cached assets); CloudFront only if needed | Avoids $0.109/GB egress for cached assets [E] |
| Network | **No NAT Gateway**: public subnets with security groups, S3 gateway endpoint | NAT costs $41/month per AZ plus $0.056/GB [E] |
| Logs | CloudWatch with short retention, structured and sampled | $0.67/GB ingested is a silent cost [E] |
| Secrets | **Infisical** stays the source; injected at runtime | Owner rule |
| Images | Built once by CI (GHCR today, ECR later), promoted unchanged | Delivery constitution rule 6 |

What stays: staging and dev on Hostinger (or Aurora Serverless at zero when idle), the agents
and Pulse on their own boxes, the AI providers as they are (AI is billed by them, not hosted
by us).

---

## 4. Cost model: per seller and per organisation

Monthly infrastructure ≈ **F** (fixed base for the phase) + **a × active sellers** +
**b × GB of audio stored**. AI is excluded (it is COGS billed per minute by the provider).

**Per-seller assumptions [A]:** 40 recorded work calls a day, 22 working days, 1.65 MB per
call [M] ⇒ **1.45 GB of audio per seller per month**; 15 analysed calls a day ⇒ ≈43 MB of
database per seller per month (130 KB each [M]); 20% of recordings played once a month.
Audio is kept 12 months, then deleted or archived (a retention decision for the owner).

| | 100 active sellers (≈20 orgs) | 1,000 (≈150 orgs) | 5,000 (≈700 orgs) |
|---|---|---|---|
| Compute (Fargate ARM: API, web, worker) | $74 (API 2×0.5 vCPU, web 1×0.5, worker 2×1) | $160 (API 4×1, web 2×0.5, worker 3× Spot c7g.large) | $520 (Compute SP applied) |
| Load balancer (ALB + LCUs) | $24 | $75 | $180 |
| Database (RDS + gp3) | $68 (t4g.medium, Single-AZ, 50 GB) | $332 (m7g.large Multi-AZ with DB SP, 200 GB) | $820 (m7g.xlarge Multi-AZ + replica, 1 TB) |
| Audio storage (S3, 12-month retention, tiered) | $22 (≈0.9 TB after 6 months) | $260 (≈17 TB) | $1,250 (≈87 TB) |
| Egress / CDN | $0 (inside the 100 GB free) | $15 (CloudFront Pro flat) | $200 |
| Logs, IPv4, cache, queue | $14 | $65 | $160 |
| **Total per month** | **≈ $200 (₹19k)** | **≈ $900 (₹86k)** | **≈ $3,100 (₹2.9 lakh)** |
| **Per active seller** | **≈ ₹190** | **≈ ₹86** | **≈ ₹59** |
| Of which audio storage | 11% | 29% | 40% |

Read the table as orders of magnitude [A]: the shape (fixed base dominates at 100, storage
dominates at 5,000) matters more than the dollars. Per **organisation**, cost ≈ sellers ×
the per-seller figure; an organisation adds almost nothing on its own (one tenant row,
settings, a few background jobs).

**Against revenue** [M, 23 Oct; internal]: an organisation seat nets ₹9,722 a month, so
infrastructure is **≈1–2% of seat revenue** at any scale; a Personal plan nets ₹2,059, so
infrastructure is **≈3–9%**. The AI minutes the same seller uses cost far more (a seller
analysing 20 four-minute calls a day uses ≈1,760 minutes ≈ ₹1,500 at ₹0.85), which is why
the plan's minute caps and the Flex route matter more than the host.

**Three levers that move the model most:**
1. **Audio encoding and retention.** Re-encoding stored calls to speech Opus at 12–16 kbps
   cuts storage about 3× against today's average [A, to measure]; keeping raw audio 6 instead
   of 12 months halves it; Intelligent-Tiering moves cold audio to $0.0138/GB [E].
2. **No NAT Gateway, no idle IPv4s, short log retention**: together these avoid ≈$50–100 a
   month of pure overhead at small scale [E].
3. **Commitments only on the floor:** 1-year No Upfront Compute Savings Plans (24–28% off on
   Graviton) and Database Savings Plans (20% on m7g) cover the steady 60–70% of usage; Spot
   covers retryable workers. Credits cannot pay upfront fees [E].

---

## 5. Triggers to move (any one is enough)

| Kind | Trigger | How we see it |
|---|---|---|
| **Revenue** | Net revenue ≥ **₹4 lakh/month** for 2 months (managed production ≈₹19k ≤ 5% of it) | Admin → Economics |
| **Capacity** | Production busy-hour CPU > 60% of its allotment for 2 weeks, or analysis queue lag > 15 min at the busy hour after the worker is made parallel | ac-efficiency, Admin → Analysis health |
| **Storage** | Audio > 150 GB, or disk free < 25% for a week | host metrics |
| **Reliability** | Two host incidents in a quarter that hit production (throttle, disk full, noisy neighbour), or RPO for audio must drop below 24 h | incident log |
| **Customer** | An organisation of ≥50 seats, or any customer asking for in-India storage guarantees, encryption key control, uptime commitments or a security questionnaire | sales |
| **Release speed** | A hotfix can't reach production in under an hour because of the shared box | release log |

---

## 6. Phased plan (each phase unlocked by its band)

| Phase | When | What | Monthly infra (approx.) |
|---|---|---|---|
| **0. Make it portable (now, on Hostinger)** | Now | Production on its **own** VPS (₹4k, already proposed); fix the launch blockers (parallel worker, the availability poll, budget-JSON growth, indexes); store audio behind an S3-compatible interface; nightly backups to an in-India bucket; images built once and promoted; infrastructure written as code (Terraform) but not applied; this cost model wired into Admin → Economics with real invoices | ₹6–7k |
| **1. Data first** | Storage or customer trigger | Recordings and backups to **S3 Mumbai** (Intelligent-Tiering, Object Lock for backups); compute stays on the VPS; Activate Founders credits applied for | + $5–30 |
| **2. Production to AWS** | Revenue ≥ ₹4 lakh/month, or capacity/reliability trigger | Fargate ARM (API, web, worker), RDS t4g.medium Single-AZ with PITR, ALB, Cloudflare in front, no NAT; blue-green cut-over with a dump/restore and a read-only window of minutes; Hostinger kept warm for 30 days as rollback; staging stays put | ≈ $200 (₹19k) |
| **3. Resilient** | Revenue ≥ ₹15 lakh/month, or ≥50-seat customer | Multi-AZ RDS (m7g.large), Savings Plans on the steady floor, Spot workers, S3 replication + snapshot copies to Hyderabad, WAF, alarms on cost per seller | ≈ $600–900 |
| **4. Scale** | ≥ 3,000 active sellers | Read replica for Admin and analytics, ElastiCache Valkey for hot reads, partitioned `analytics_events`, Aurora I/O-Optimized only if I/O ≥ 25% of database spend [E] | ≈ $2–3k |

**The revenue rule that keeps spend proportional:** each month, Admin → Economics compares
hosting (invoice) with trailing-3-month net revenue. Above 6%, the next phase waits and the
team looks at the levers in §4; under 3% with a trigger firing, the next phase is due.

---

## 7. Migration method for phase 2 (when it comes)

1. Write the stack as code; stand it up in an AWS account on the Paid plan with Activate
   credits; restore a production snapshot into it (no live traffic).
2. Run `wb-ci --e2e` and the canary against it; compare tap-to-response by device tier with
   the release gate (it should not regress).
3. Owner approval under OWNER-APPROVED DATA CHANGES for the cut-over window; snapshot first.
4. Freeze writes for minutes, final dump/restore and audio sync, switch Cloudflare origin,
   canary, unfreeze.
5. Keep the Hostinger production read-only for 30 days, then retire it.

---

## 8. Risks and what would change the answer

- **AI is the cost, not hosting.** If v2 on Flex lands (₹0.36 per plan minute), margins
  improve far more than any hosting choice.
- **Indian clouds** (E2E Networks at about $36/month for 4 vCPU/8 GB [E]) or Azure Central
  India (D4ps_v5 ≈ $74/month [E]) are cheaper for raw compute; AWS wins on managed Postgres,
  S3 in two Indian regions and the tooling the agents already know. Revisit if AWS's base
  cost blocks phase 2.
- **Unknowns to measure:** real recorded calls per seller per day, audio size after a codec
  change, playback rate, and how many sellers an organisation really has.
- **Not verified:** India-specific AWS startup programmes; KeyBanc and ICONIQ hosting
  benchmarks; the Hostinger data centre our account uses (see `05a-aws-unit-prices.md`).

Sources: unit prices and their URLs in `05a-aws-unit-prices.md`; measured inputs in the 22 Oct
launch capacity audit and the 23 Oct unit-economics note (shared notes), and Admin →
Economics.
