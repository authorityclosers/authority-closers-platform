# AUT-1801: automatic display role attribution

Source base: `a5c71f8`. The existing server speaker-map predictor is used;
no provider, C5 prompt, identity or confirmed attribution is activated here.

The original company-introduction cue matched bare `our team` and an
unbounded `I am ... from` span. Buyers discussing their team or moving away
from reception could therefore accumulate seller cues. Common English,
Hindi and Marathi self-introductions did not match. Repeated buyer questions
then outweighed the actual caller's introduction and reversed the roles.

The repaired cue recognizes bounded self-introductions, including `name here
from`, Hindi `मैं name, company से`, Marathi `मी name, company मधून` and mixed
Marathi `name बोलतोय, company मधून`. Generic team/company mentions and a
lowercase `I am moving away from` clause do not become self-introductions.
A unique explicit introduction takes precedence over repeated weak questions.
Two introductions remain ambiguous. With more than two voices, unassigned
voices do not become prospects by elimination.

These remain `predicted` display roles with evidence and
`text_predicted_roles` provenance. They do not establish account ownership,
confirmed/channel attribution or role-specific measurement authority.
Existing confirmed, channel and model precedence is retained.

## Independent synthetic text diagnostic

The private diagnostic used the original 60 audio-selected synthetic
transcripts. Only their words, opaque speaker IDs and estimated clocks reached
the predictor; participant names, roles, phase, annotations, CRM and outcomes
were held out. Expected roles came from explicit fixture participant labels.
No account name was supplied. No provider calls or canonical state writes
were made.

| Diagnostic | Correct speaker decisions | Wrong | Unresolved |
| --- | ---: | ---: | ---: |
| Existing predictor | 8 | 74 | 48 |
| Repaired predictor | 110 | 0 | 20 |

There are 130 speaker decisions across the 60 calls. The unresolved decisions
are the prospect and extra voice in the ten three-person calls. All 60 seller
predictions agree with the fixture; the other 50 two-person calls also have
the expected prospect. This is ideal fixture diarization with repeated
synthetic scaffolding, not independent real-call accuracy or verified audio
alignment. The separate staging report scorecard remains unreviewed.

The private artifacts, grouped by language and business, are under
`/home/acdev/strikes/1801/quality/`. The diagnostic was repeated after each
matcher/precedence change; prior outputs were preserved. Tests cover positive
introductions in all three languages, repeated buyer questions, team mentions,
location clauses, conflicting introductions, extra voices, source immutability
and provisional provenance, alongside the existing speaker-map/service suites.
