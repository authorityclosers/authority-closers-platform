# Dipak visual asset provenance gate

Date: 2026-09-03
Workstream: AC-WF-LEARNER-V1
Status: **blocked — no new identity-bearing generation**

## Decision

The v1 Dipak visual set is not generated in this pass. A person-specific
dashboard hero/video poster, course thumbnail containing Dipak, or profile
avatar requires an approved source photo and a traceable rights/consent record.
The current repository manifests do not contain an exact Drive ID/URL for such
a photo, and the connected Drive image search did not return one. Generating a
plausible person from an unverified public portrait would create an identity and
provenance claim that the evidence does not support.

The existing dipak-learning-hero-v1.png file is preserved byte-for-byte and
marked quarantined_public_evidence in asset-manifest.json. It remains a
historical staging candidate only; it is not a production avatar, identity
asset, lesson/video media, course thumbnail, or canonical content fallback.

## Authority and source checks

The exact controlled source register is
docs/traceability/CONTROLLED_SOURCE_REGISTER.md. The required source order was
reviewed before the asset decision, including:

| Source | Exact Drive ID | Role in this gate |
| --- | --- | --- |
| Authority Closers Master Index | 1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus | Source order and precedence |
| Approved BRD | 1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk | Approved product boundary |
| AC-IMP-00 | 10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A | Capability gates |
| AC-IMP-01 | 1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU | Controlled source and forbidden actions |
| AC-IMP-03 | 1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo | Identity/provider guardrails |
| AC-IMP-04 | 1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc | Free-course/media boundary |
| AC-IMP-05 | 1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw | Acceptance and evidence gates |

The connected Drive connector was callable and used read-only. Searches for
Dipak Vishwakarma, headshot, portrait, and photo, restricted to image items,
returned zero results. A browse of 75 accessible image records returned zero
identity-matching titles. The image reference prompt pack
(1cVSuld6Ugzg0KpX9c5BttfzvJt2vhbZw:
https://drive.google.com/file/d/1cVSuld6Ugzg0KpX9c5BttfzvJt2vhbZw/view?usp=drivesdk)
contains generation rules and generic UI references, not a Dipak source photo.
The raw founder direction PDF
(1T5cLrKjnE_5Z_Dhgkj20dxvTYpjX1Rk5:
https://drive.google.com/file/d/1T5cLrKjnE_5Z_Dhgkj20dxvTYpjX1Rk5/view?usp=drivesdk)
is context evidence, not a photo asset or rights grant.

## Public founder evidence (non-authoritative)

The public homepage https://dipakvishwakarma.com/ identifies Dipak Vishwakarma
as the founder of Authority Closers and exposes portrait paths including:

- /_next/image?q=92&url=%2F_next%2Fstatic%2Fmedia%2Fdipak-seated-armchair.3qozyuzikzdpv.png&w=2560
- /_next/image?q=92&url=%2Fhero%2Fdipak-seated-mobile.png&w=2560

This observation helps disambiguate the public founder context only. The page
is not a controlled asset register and did not establish subject consent,
Authority Closers derivative-use permission, license scope, retention/expiry,
or a Drive-backed source record. No website image was downloaded into the
repository or used for new generation in this pass.

## Required evidence to unblock generation

1. An exact Drive file ID and URL for every approved source photo, with access
   verified by the asset owner.
2. Written subject/owner consent naming the permitted surfaces: dashboard hero,
   video poster, course thumbnail, and/or profile avatar.
3. A rights/license statement covering derivative crops, image-generation
   derivatives, staging/public distribution, takedown, and expiry.
4. Source provenance and retention metadata, including the canonical source,
   date, owner, revision, and supersession/takedown path.
5. Approved desktop, mobile, and square crop guidance plus identity review.
6. Separate approved course/media copy and media rights before using any image
   as a course thumbnail or video poster; generated art cannot stand in for an
   approved lesson asset.

Once those records exist, issue separate ImageGen jobs for desktop and
mobile-safe hero/poster compositions, the approved thumbnail pair(s), and the
square avatar. Preserve each original generated file and record its prompt,
source ID, SHA-256, crop review, and QA status in the manifest. Until then, keep
all requested records blocked_provenance and render an honest placeholder or
empty state in product surfaces.

## Existing candidate inspection

apps/learner-web/public/media/dipak-learning-hero-v1.png was inspected at its
native 1672x941 dimensions. It has a stable SHA-256 of
91c49f07323dfe3ccd4e477c0b598cad3d131c7ac6557fe87019b43e4178fb86 and was
preserved unchanged. The wide composition has copy-safe dark space on the left
and a person on the right, but the person-specific appearance cannot be
validated against an approved source record; therefore visual quality does not
clear the provenance gate.
