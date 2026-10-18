# Production as the one real database, copied down (design, not built)

Owner order, 19 Oct 2026: production is the one real database. Staging and dev get its data copied down, their own writes stay local, and nothing writes back.

His two conditions:
1. Erasing something on production erases it in the copies too.
2. Client companies' calls (for example Wise Life) are copied only if he decides so. Authority Closers' own data is fine to copy.

Status: design only. Nothing here is built or switched on.

## In plain words

Every hour a copy job reads production, read-only, and brings staging and dev up to date:

- **What is copied.** Only Authority Closers' own companies, plus any client company the owner has said yes to.
- **What stays on the copies.** Anything staging or dev made itself (test calls, edits) stays there and is never sent back.
- **When production and a copy disagree, production wins.**
- **Erasure.** Every 5 minutes a smaller job copies down only erasures, so an erased call disappears from the copies within minutes.
- **What is never copied:**
  - payments and billing;
  - sign-in sessions and passwords;
  - provider keys;
  - anything that would make staging or dev contact a real customer.

## The shape I recommend: a pull job, not database replication

```
production postgres ──(read-only export: allowed tables × allowed companies)──▶ copy job ──(upsert by id, prod wins)──▶ staging / dev postgres
        │                                                                          │
        └── erasure log (erased ids, every 5 min) ─────────────────────────────────┘──▶ erase same ids + their audio on the copies
```

It works like the metrics collector already running on the host:

- **The job.** A root timer runs one fixed export inside production's own postgres container, read-only. It writes only into the staging and dev databases.
- **Its rules live in the repo, so they are reviewed and released like code:**
  - a table list, saying which tables are copied, excluded or transformed;
  - a company allow-list, which is the owner's decision.
- **Rows are matched by their id:**
  - a production row is inserted or updated on the copy;
  - a row the copy made itself (an id production doesn't have) is never touched.

**Why not PostgreSQL logical replication** (production 18.6 supports row filters):

- **Production disk.** A replication slot keeps production's write-ahead log growing whenever staging or dev is down or stuck. That is a real disk risk on this 4-vCPU, 84%-full host.
- **Migrations.** Staging runs newer migrations than production, and replication breaks on dropped or renamed columns.
- **Unique clashes.** One clash stops the whole subscription. An example is an email that a tester also used on dev.

A pull job fails one run, reports it, and tries again; production never notices.

## The two conditions, built in

**1. Erasure reaches the copies.**
- Every production erasure is already a recorded change: the `erased_at` columns and the retention scheduler. The copy job reads the ids erased since its last run and erases the same ids on each copy, including the copied audio and checkpoints, every 5 minutes.
- The job also re-checks every copied id against production once a day, so nothing is left behind if a run was missed.
- An alarm fires if any copy is more than 30 minutes behind on erasures.
- **Prerequisite:** AUT-2090 first. Production erasure today leaves transcripts and analysis checkpoints behind. Copying would spread that gap, so the full erasure must exist on production before copying starts.

**2. Client companies are copied only on the owner's yes.**
- The company allow-list starts with Authority Closers' own tenants only.
- Adding a client (for example Wise Life) is a one-line change that names the owner's approval and the date. It shows in Admin as "Copied to staging/dev: yes, approved 19 Oct by Suyash".
- Removing a client erases its rows from the copies on the next run.

## Safety rules for the copies

- **Never copied:**
  - sessions and tokens (a production session on dev would be an account takeover);
  - password and credential tables;
  - billing and payments tables;
  - provider keys;
  - partner webhook secrets;
  - the budget and hold ledger.
- **Copies can't reach real people.** Staging and dev keep outbound email, phone alerts and partner webhooks off for copied companies, so a copy can never message a real customer.
- **Dev is the widest-open environment**, because many agents can read it. Copied client data on dev shows contact details (phone, email) masked unless the owner says otherwise.
- **Copy, metrics, erasure.** The metrics store already counts a copied row once, in the environment it ran in, so copied calls won't inflate dev's or staging's spend.

## Build steps (when the owner says go)

1. AUT-2090: full erasure on production (prerequisite).
2. Table classification file and company allow-list, with tests that fail when a new table has no classification.
3. Copy job, dry run first. It prints per table and company what it would insert, update and erase, and never writes in that mode.
4. Rehearsal on a restored production snapshot, with a byte-for-byte check that local rows survive and erased ids vanish.
5. Switch on for dev only, then staging. Add Admin rows for "last copy", "erasure lag" and "companies copied".
6. Record it as an owner-approved data change kind (AGENTS.md), with each run logged.

## Open decisions for the owner

- Copy Wise Life's calls to staging and dev, or keep them on production only? Default: not copied.
- Copy the audio too, or only transcripts and reports? Default: audio for Authority Closers only, so pipelines can be re-run on real calls.
- Should dev get copies at all, or only staging? Default: both, client data masked on dev.
