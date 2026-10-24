# Release pipeline blockers, 1 to 24 Oct 2026

Owner, 24 Oct 2026 (~13:20 IST): "why does it block things so often, we need to improve the release pipeline to
reduce the time for release … if root is blocking … do something about it".

**Owner summary**
1. Between 11 and 23 Oct there were 188 ship attempts. 71 stopped (38%), costing about 91 hours of release delay. A clean release takes about 60 minutes.
2. Two thirds of the stops (46 stops, 25 hours) came from the release PR's checks. They failed on workbench code that had not had a full test run on that exact commit before it shipped.
3. Most of the remaining delay is fixed already: native image changes caused 30 hours before the guard went in on 12 Oct, and late migration checks caused 15 hours before the fix on 24 Oct. GitHub and CI outages cost 10 hours; deploy and canary failures cost 10 hours.
4. Root blocks in one place: the staging schema export that every migration release needs. It is published by hand, expires each day, and is refused while GitHub's artifact inventory is changing. v0.87 is waiting on it now (AUT-2214).
5. Fixes: require a green full wb-ci on the exact commit before shipping, rehearse migrations on the server instead of through a GitHub artifact, retry GitHub reads, and stop re-running the tests on main (saves about 19 minutes per release).

**Method.** The source is `/var/log/ac-ship.log`, which covers 11 Oct 15:42Z to 23 Oct 22:46Z, together with the per-deploy logs in
`/var/log/ac-release/`, the GitHub job logs and the Root cards. Hours lost are measured from a stopped attempt's start to the next attempt at the same version; when the next ship was a different version, only the stopped attempt's own length counts. These are calendar hours, so nights are included.

| # | Root cause | Stops | Hours | Detail | Status / fix |
|---|---|---|---|---|---|
| 1 | The workbench ships without a full green run on that exact commit, so the release PR is the first full test | 46 | 25.2 | Failing checks: Python tests 15 (some were apt mirror timeouts, AUT-2188), frontend 13, `validate` 8, browser acquisition 6, Python static and gates 9, image packaging 1, visual advisory 1. Seven stops were on checks that branch protection does not require; `ac-ship` stops on any failed check. Worst run: v0.70, 5 stops in 7 h | **Open.** `ac-ship` should refuse a commit with no green `wb-ci --full` on that exact SHA. wb-ci now also runs the migrations and control-plane gates. Advisory checks should not stop a ship |
| 2 | Native image inputs changed inside an ordinary release (11 to 13 Oct) | 4 | 30.5 | `native reuse proof refused: native_inputs_changed` on staging core (v0.40), staging web (v0.41) and production (v0.41). One of these waited overnight (23.7 h). Since then the guard has stopped one ship before its PR (v0.71, no time lost) | **Fixed 12 Oct.** The `ac-ship` native guard now stops before the PR; there have been no losses since |
| 3 | Migration checks ran only on the release PR | 7 | 15.3 | Lock-safety rules (v0.47, v0.52, v0.69), a rewritten released migration (v0.69), stale staging evidence (v0.48), a failed rehearsal command (v0.85), and CHECK text compared as raw dump text (v0.86, 11 h) | **Fixed 24 Oct** by 3572ab22, 366a8bd8, 75b19015 and a8216e17: the wb-ci migrations job runs on every commit. See `migration-safety-root-causes-20261024.md` |
| 4 | Staging schema evidence is published by hand through GitHub's shared artifact pool (Root) | 4 P0 cards (+1 stop in row 3) | open | Each migration release needs a fresh export, which has a 24 h maximum age and a one-day retention: AUT-2025 (0.4 h), AUT-2065/2066 (0.4 h), AUT-2177 (blocked since 21 Oct) and AUT-2214 (blocked today). Both blocked cards fail the complete-inventory guard while 5,842 artifacts change during pagination (AUT-2185) | **Design filed** (see below). Rehearse on the server against live staging, with no GitHub artifact |
| 5 | GitHub API and CI infrastructure | 4 | 9.5 | Inventory read hit a TLS timeout (v0.70; ac's disk was then 100% full, AUT-2173). API rate limit hit (v0.76). Main build failed twice from apt mirror timeouts (v0.83, v0.85). 6 of the last 12 main builds needed reruns | **Open.** Retry `ac-ship` API reads with backoff, bake the CI prerequisites (AUT-2188, in review), and run fewer main jobs (cut 1) |
| 6 | Deploy safety | 5 | 10.2 | The worker did not drain and the rollback was incomplete, so staging and production were down (v0.57, AUT-2092/2095). Staging canary failed on provider HTTP 402 (v0.49, 6.2 h, AUT-2032). Production canary failed with v0.69 left live (cause not kept). v0.50 was refused for a version gap after v0.49 failed on staging | Partly fixed. AUT-2032 is still blocked. Canary output should be kept with the ship log |
| 7 | Process and tooling | 5 | 0.3 | single-track lane overlap (3), PR already open (v0.73), commit not containing main (v0.46). Owner corrections (v0.62, v0.63) are not counted | Minor |

**1 to 11 Oct (train mode, before `ac-ship`; Root card open times, which are upper bounds rather than measured delay).** The same
families appear: staging release paused (AUT-665 35 h, AUT-1830 26 h, AUT-1930 56 h), a missing core release artifact
(AUT-1216, 106 h), a native input refusal (AUT-1361, 27 h), and staging smoke failed (AUT-1804, 102 h). The artifact pool
card AUT-1036 has been blocked since 3 Oct. 128 "Train alert" cards were raised; 80 of them said "staging core is behind green main".

**Where a clean release's hour goes** (medians, 11 to 23 Oct):

| Stage | Time |
|---|---|
| Release PR CI | 13 to 20 min |
| Main validation and images | 23 min (28 min since 21 Oct) |
| Staging core and web deploy | 7 min |
| Staging canary | 1 min |
| Production backup and core deploy | 4 min |
| Production canary | 1 min |

On main, the tests (17.6 min) re-run on the same tree the release PR has just passed, before packaging (10.6 min) can start.

**Two biggest cuts to the clean path (about 60 min now, about 35 min after both).**
1. **Stop re-running the tests on main (saves 18 min).** Main's Application validation spends 17.6 min re-running the tests on the tree that
   the release PR has just passed. `ac-ship` already proves the squash commit's tree is identical. Packaging the images
   right after the merge would make main take about 11 min instead of about 29, and would roughly halve the exposure to apt mirror reruns. A safe first
   step with no change to trust: start `package-release-images` in parallel with the tests, with the deploy still waiting for all of them.
   That alone saves about 10 min.
2. **Shorten the Python test critical path (saves about 8 min on both the PR and main).** On v0.86 the four required shards took 11.6, 12.5, 14.8 and 16.4 min,
   unbalanced. wb-ci runs the same suite in 17 shards of 5.6 min or less. Rebalancing by measured durations, or fanning out more
   runners under the same four required check names, brings PR CI from about 18 min to 8 to 10 min. Baking the CI prerequisites (AUT-2188) removes
   1 to 3 min per job and the mirror-timeout reruns.
Both changes are to CI workflows only (shared files), so they need CTO review.
