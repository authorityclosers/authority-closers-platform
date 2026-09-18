# AudioAtlas prerequisite for a clean CI checkout

CI34731858764 reached all application tests but many conversation PostgreSQL and
browser fixtures failed when their local inspection job could not start. The
Sales lane identified the common missing prerequisite: the ignored native
AudioAtlas binary and its build manifest existed on the Windows development
machine but were absent in a clean Linux checkout.

The source deliberately refuses processing without a binary matching its
reviewed source/build hashes. CI now explicitly checks the C++ compiler, builds
through `signals.build_native`, and validates the resulting executable through
the same manifest/source/binary check before application tests. No worker or
processing guard changes, runtime compilation, skipped tests or external calls
are introduced. Hosted native runtime packaging remains a separate activation
requirement; this CI prerequisite alone does not activate Sales processing.

Validation: the five recovery/CI prerequisite tests pass; Ruff lint/format,
workflow Prettier and diff checks pass. Exact clean-Linux compilation and the
affected PostgreSQL/browser tests remain mandatory in the next CI run.
