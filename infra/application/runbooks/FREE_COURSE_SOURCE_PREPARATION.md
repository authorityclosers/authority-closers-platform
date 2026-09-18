# Free Course source preparation and release

This runbook records the actual staging and production Coach drafts created on
2026-09-13. Existing GLOBAL catalog, enrollments and progress remain immutable.
Use the application commands with the current authenticated operations owner;
never supply a fabricated actor or use direct SQL recovery writes.

## Actual sources

| Environment | Operations tenant | Verified owner | Source program | Draft version |
| --- | --- | --- | --- | --- |
| Staging | f5386fc3-033d-4e75-a333-7774381cb4d5 | 311f4bd2-7b8b-4f45-99f0-a2aed83bc95a | 189cec59-e302-4fe3-8215-a34c68e394a9 | 4bdddd8a-e097-42dd-80c9-884b6482da21 |
| Production | fb594dea-fdb6-444c-a36f-1d94fbc65bbf | 033b7038-154a-4e5a-8a23-8d5ffeec2b4b | a1993f11-f43d-446a-821f-550bc40b950c | 11996bb5-a4ce-4b18-8785-0a233a4c562c |

The staging owner is admin@authorityclosers.com. The production owner is
Dipak at dipak@authorityclosers.com. The personal staging Dipak learner
1379f28f-88c1-49d2-ab89-31f7ed65223e is a separate identity; do not merge or relabel it.
Both source editors have four module titles and five required Module 1 activities.
Modules 2–4 contain no activities in the reviewed baseline. Do not describe them
as completed teaching material or invent missing lecture content.

1. SHIFT 1 — Why High-Ticket Sales Is A Completely Different Game.
2. SHIFT 2 — “I’ll Think About It” — What Your Prospect Is Really Telling You.
3. SHIFT 3 — The Call Felt Great. So Why Didn’t They Buy?
4. SHIFT 4 — The Story That’s Stopping You From Becoming A High-Ticket Closer.

Module 1 has VIDEO, REFLECTION, IMPLEMENTATION_CHALLENGE, REVIEW and IMPROVE.
The VIDEO title is “4K playback test — Big Buck Bunny”. Its saved instructions
identify technical testing, Blender Foundation (2008), Janus Bager Kristensen
(2013) and CC BY 3.0. This test film is not a course lecture.

## Prerequisites before source publication

Wire M2→M1, M3→M2 and M4→M3 through catalog.cli wire-prerequisite. Each command
resolves the canonical session, applies server-owned role permissions, validates
the exact source graph and appends an audit receipt in the same transaction.
Preserve these intent IDs for replay after an uncertain response:

| Environment | Modules M1, M2, M3, M4 in order | Command IDs for M2, M3, M4 |
| --- | --- | --- |
| Staging | d2c63b1e-8c39-4cf4-a24d-08fea214f9f7; 3b0cb2c6-7961-423f-8f00-835f5c70d783; ded19cf2-7235-40ca-9ae0-33a6a5151855; 224ce9d1-32f8-41d0-92dc-659503dc06ea | 478ccdb0-2609-59ea-8b7a-4cb8a5549ee8; f7e2ee37-7338-57d3-91cf-bfb937b69f6a; 6a9dd64a-928e-5adc-97ed-b084b576a01f |
| Production | 7b383db6-b50b-4265-9883-3b0c4dbb5bb7; 170ebc49-7976-4538-89ed-e1000c1e573a; ef4ace8a-3d60-48ea-93db-0282c206116e; 7548f774-d497-4bcd-ba6c-f8da473c7710 | 6cc5db79-425d-5605-afac-d0a19de95b13; f9db629e-0994-58c5-8962-d6ab166285bd; 3474fbb5-a08b-55fc-97de-8daea208dd97 |

The initial runtime 41d3c5726a1b5d217259c034bf058d9107135b1f does not contain
this new prerequisite CLI command. Its one-shot operator must load the exact
reviewed b47523a798b22bf04095b870361be8cdd4681575 CLI blob in memory through
reviewed private transport. Do not assume a helper exists under current-staging
or current-production, change an image file, or run host Python without the
application environment. Later releases containing this CLI can run it normally
inside their verified API container. Session values never belong in commands,
logs, files or this runbook. Wire the draft before publication makes it immutable.

## Tracked video upload and publication

After the exact release is deployed and the media filesystem/scanner/worker are
ready, use the normal Coach upload-intent, stream, completion and READY path.
The existing reviewed SSH uploader preserves Coach authentication and sends
bytes through the local ingress to avoid the public proxy request-size ceiling.
It does not create untracked media files.

The cached full source is 633016449 bytes, 3840×2160, 634.6 seconds, SHA256
37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520.
The requested upload ceiling is 2000000000 bytes. Record actual upload_id,
source_asset_id and READY MediaVersion ID; a course ProgramVersion is not a
MediaVersion and must never be substituted for promote-media source-version-id.

Staging uses adopt-existing command 6c0295c6-9976-5d74-933e-e420f6a40d99:
GLOBAL program a6382ab5-63f5-562c-bfa8-1bdd944194c2, version
67e08626-9b3d-50d2-b9c1-5a44645d5114, VIDEO
73dfbbf7-5f2c-5e88-ad27-e5c84c65690f, public tenant
206ccee8-a246-433b-b6d3-78eb21592a5c. Adoption independently checks the
existing reviewed digest ac173fbeb705c6640ad08e5febf4c692db5d16218fd9d08ca71aac68564a0440
and preserves GLOBAL content and progress. The owned source may remain a draft.

Production has no existing GLOBAL course. Use publish command
0cf4c903-c6fb-4637-a01e-9818abfd71f1 with public tenant
c1d51741-6e0f-4ddc-8cc4-58856d0e778f. The reviewed publication v3 transport
records the actual execution UTC timestamp, actual source/testing attribution
and the real release. Do not copy historical staging review timestamps or claim
a nonexistent external review. Record the actual returned GLOBAL program,
ProgramVersion and VIDEO activity. Do not use the unused production adoption ID.

Finally use canonical promote-media with the actual READY asset/MediaVersion,
actual publication/adoption receipt and the corresponding verified owner:
staging intent d5c94ca1-f75d-5fd5-9515-4f1692dbe121; production intent
3aa3729f-65c4-53b5-83a3-fbf1a9234d32. No source/media/binding identifier may be
inferred from another identifier type. Preserve any existing binding by its
explicit supersession path when required. Completion requires real learner
playback and seeking, including a mobile viewport; READY alone is insufficient.
