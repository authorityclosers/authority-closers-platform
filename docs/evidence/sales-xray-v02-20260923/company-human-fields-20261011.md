# Human Company field contract — AUT-1677

The prepared human command validator admits only name, industry, city and business size as literal text, plus explicit Unknown for the latter three. It reuses the existing text/Unknown value primitives and detached field descriptors. It preserves Devanagari, ranges, approximation and units as typed; it does not rename a person's team size, convert numbers, add contacts, match identity or accept evidence/actor/lock metadata from a command.

Validation: 55 focused Company human-field, company-profile source/subject and existing prospect-field cases pass; strict module mypy and ruff pass. This pure contract mounts no API and writes no data. Company identity/revision/link schema preparation remains a private verified checkpoint while the production-login PR #442 holds the shared migration slot.
