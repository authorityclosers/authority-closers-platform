# Academy capacity simulation validation evidence

- Evidence date: 2026-09-04
- Source: `tools/simulations/academy_capacity_sim.cpp`
- Scenario ledger: `tools/simulations/academy_capacity_scenarios.csv`
- Published result data: `docs/research/academy-capacity-simulation-results-2026-09-04.csv`
- Toolchain: Microsoft C/C++ Optimizing Compiler 19.44.35217, C++17, x64,
  `/W4 /WX /O2`. The harness pins the 19.44 compiler family and fails closed on
  another family until the published baseline is deliberately reviewed.

## Validation command

```powershell
& .\scripts\Test-AcademyCapacitySimulation.ps1
```

## Recorded result

```text
academy_capacity_sim.cpp
self-test: PASS
erlang-c theoretical mean wait hours: 0.44444
simulated mean wait hours: 0.44038
simulating ac_dipak_pilot_25 (5000 runs)
simulating ac_cohort_100 (3000 runs)
simulating ac_launch_250 (2000 runs)
simulating future_5_tenants_supported (1000 runs)
simulating future_5_tenants_understaffed (1000 runs)
academy-capacity-simulation: PASS
compiler: MSVC 19.44.35217
```

The M/M/c reference exercise used 400,000 measured arrivals after a 10,000-arrival
burn-in. Its simulated mean queue wait differed from the analytical Erlang-C result by
0.91%, within the executable test's 6% tolerance.

The five operational scenarios comprise 12,000 Monte Carlo cohort replications,
3,425,000 simulated learner trajectories, and approximately 10.29 million generated
human-work jobs. Fixed seeds reproduce the published run on the pinned MSVC
19.44 toolchain; the harness compares every generated CSV field with the
checked-in publication so a standard-library or implementation drift fails.

## Executable assertions

1. Working-calendar service crosses a configured non-working day correctly.
2. The continuous M/M/c queue agrees with the Erlang-C analytical mean wait within 6%.
3. Re-running a cohort with the same seed reproduces activation, completion, job counts,
   and turnaround values exactly.
4. Zero review and zero intervention probabilities generate no human-work jobs.
5. Non-finite inputs and scenarios above bounded work/memory caps fail closed.
6. The scenario run emits the five expected rows in order.
7. Completion and service-target percentages are finite and remain inside
   `[0, 100]`.
8. Every generated field matches the checked-in published CSV exactly.

The Application validation workflow runs the same harness on a GitHub-hosted
Windows runner, so result drift and compiler-family drift block the PR rather
than relying only on a manual reproduction.

## Non-claims

This evidence validates the simulator's queue mechanics and reproducibility. It does not
validate Authority Closers learner behavior, learning efficacy, a staffing commitment, a
commercial forecast, an assessment rubric, or an official AI score. Activation,
continuation, review fraction, service time, coaching availability, and telemetry density
are declared scenario assumptions that must be recalibrated from consented pilot data.
