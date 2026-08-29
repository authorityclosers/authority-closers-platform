# authority-closers-platform

Permanent Authority Closers Learning & Practice OS implementation repository.

Bootstrap target:
- Next.js/React learner app
- separate admin surface
- FastAPI/Python backend
- PostgreSQL canonical state
- versioned Program/Module/Activity
- transactional outbox + durable jobs
- provider ports/adapters
- OTel-compatible observability
- reproducible local/dev/staging/prod deployment

Do not begin by building every surface. Follow AC-IMP-05.

## Local foundation

Prerequisites: Node 24, pnpm 11, Python 3.12/3.13, uv, and Docker.

```powershell
pnpm install
uv sync
pnpm dev
```

This starts pinned PostgreSQL, Mailpit, and Jaeger dependencies plus the learner app on `http://localhost:3000`, admin app on `http://localhost:3001`, and API on `http://localhost:8000`. Provider side effects remain held and email remains fake by default.
