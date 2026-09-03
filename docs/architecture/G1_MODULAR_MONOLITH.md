# G1 modular monolith

Controlled references: AC-IMP-04, AC-IMP-05, AC-G1-001–020, ADR-024, ADR-025.

```text
learner-web ─┐
             ├── versioned FastAPI boundary ── PostgreSQL canonical state
admin-web ───┘              │
                            ├── transactional outbox + durable jobs
                            ├── replaceable provider adapters
                            └── OpenTelemetry signals
```

The Python package is one deployable domain system. Modules communicate through commands, queries, and explicit ports. They do not import another module's persistence internals. PostgreSQL is canonical; analytics, provider callbacks, and UI state never grant access or progress.

Initial permanent modules are identity, tenancy, catalog, enrollment, learning, certificates, administration, audit, outbox, providers, telemetry, database, application, and HTTP. Redis, Kafka, Kubernetes, autonomous official scoring, paid commerce, voice, community, WhatsApp, and broad B2B UI remain disabled.

Every provisional contract carries a source-gap reference and remains replaceable until the controlled Drive set assigns its permanent route/entity/component identifier.
