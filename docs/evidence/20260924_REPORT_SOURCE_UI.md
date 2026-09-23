# Report source UI integration

The bounded report slice adds optional skill evidence to the existing report reader. A skill note shows the saved observation, exact supplied transcript excerpts and times, and a Listen action using the existing authorized audio player. Coaching-document references remain separate from recording excerpts. Legacy reports without dimension evidence remain readable and explicitly show that no excerpt was supplied; the frontend does not invent an explanation or source.

The root report contract validates optional evidence before rendering, including source segment, quotation and native times when the transcript is available. This is compatible with legacy reports and the versioned coaching-v5 response. A generated report must still pass semantic quality review; matching a quote is not proof of the interpretation.

The integrated source checkpoint is `80abdca8`, with the root evidence parser and account-first integration. The focused standalone, SalesSkills, report-contract and AcquisitionStudio selection passes 115 tests. ESLint and the optimized Next build, including TypeScript, pass. An independent local read-only review found no concrete blocker in the excerpt/seek connection; that review did not run tests.

No v5 provider report or production activation is claimed. This is a single-call presentation change, not implementation of full Brain 3 persistent learner history or cross-call coaching.
