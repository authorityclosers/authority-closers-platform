# Human Unknown field locks — AUT-1677

An existing supported human field command can record Unknown. That human revision already wins over later detected values; the read projection now retains its person/lock/time metadata. Prospect Information and Report Key facts show the lock beside Unknown. Unset fields keep their older two-key representation. No old value, source quotation or detected disagreement is attached to a human Unknown.

Validation on main a5c71f8 integration:

- 64 focused profile codec, Prospect Information, Report Key facts and Company/shared-fact cases pass. Incomplete or invented Unknown lock metadata is rejected; old unset Unknown responses still open.
- The focused PostgreSQL field-history test passes (27.69 s): a human Unknown followed by another source-backed detection stays locked on API read-back, exposes no old value/source, and retains existing sensitive-source and immutable-history assertions.
- App typecheck, changed-file ESLint/Prettier and Python ruff pass.

This changes read metadata and its display. It introduces no clearing control, write permission, schema change, provider request or deployed verification claim.
