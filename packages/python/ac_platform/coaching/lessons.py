"""Text teaching grounded in the owner's binding Coaching specification.

Do not silently adopt an unapproved training/profile candidate as knowledge.
The impact/discovery framework is explicitly taught in Coaching §3. Other
skills use the spec's own-call comparison method and the source-bound mission;
they do not acquire an invented subject-specific framework.
"""

from ac_platform.coaching.contracts import Mission, Moment, TextLesson

SOURCE = "Owner's Sales Xray specification, 9 Oct 2026 · Coaching §3 and §5.6"


def lesson_for(skill_id: str, moment: Moment | None, mission: Mission) -> TextLesson:
    impact = skill_id in {"discovery_deep_understanding", "problem_impact_desire"}
    if impact:
        # Spec §3.1–3.5, the blog-style text lesson, without the example's names.
        return TextLesson(
            title="Understand the impact before you present the solution",
            quick_idea=(
                "Good discovery is not about asking more questions. When a prospect tells you "
                "a problem, your job is not to prove at once that you can solve it. First "
                "understand what that problem is actually causing."
            ),
            framework=("Problem", "Impact", "Desired outcome", "Then solution"),
            why_it_matters=(
                "The prospect already knows the problem. Until its cost is clear, your solution "
                "can feel useful but not necessary. Impact gives the buyer a reason to change, "
                "and it makes the value and price conversation easier later."
            ),
            good_looks_like=(
                "Stay with the problem long enough to understand one or more real consequences: "
                "lost revenue, time, effort, slow growth, stress or risk. Use the prospect's own "
                "words. Don't fill in a number or a feeling they haven't given you."
            ),
            better_direction=mission.behavior,
            example_wording=(
                "What usually goes wrong when that happens?",
                "How much of your week goes into dealing with it?",
                "What does this stop you from focusing on?",
            ),
            when_to_use=(
                "When the prospect raises a real problem and what it costs them is still unclear. "
                "Check what they have already told you first."
            ),
            when_not=(
                "Don't keep asking impact questions once the consequence is clear and the "
                "prospect has given enough detail. Don't repeat a question they've answered or "
                "push after a clear no. The goal is clarity, not interrogation."
            ),
            checklist=(
                "Is the problem clear?",
                "Is the impact clear?",
                "Is the desired outcome clear?",
                "Only then move to the solution.",
            ),
            source=SOURCE,
            own_call=moment,
            next_call_connection=mission.behavior,
        )
    return TextLesson(
        title="Turn this moment into one better response",
        quick_idea=(
            "Start with what actually happened on the call. Then pick the one change that "
            "would have helped most. Keep your own words and style; this is a guide, not a "
            "script. It comes from Sales Xray's reading of your call, so you can disagree."
        ),
        framework=(
            "Replay the moment",
            "Ask what it needed",
            "Pick one better response",
            "Try it on a real call",
        ),
        why_it_matters=(
            moment.observation
            if moment is not None
            else "One clear change is easy to try and easy to check on your next call. "
            "This is general practice, not a weakness found on this call."
        ),
        good_looks_like=(
            "Listen to the moment in full, including what the prospect had already said. "
            "Say the change in words someone else could notice. Practise it the way you "
            "naturally speak, then use it only when the same kind of moment really comes up."
        ),
        better_direction=mission.behavior,
        example_wording=(),
        when_to_use=mission.context,
        when_not=(
            "Don't use it when the situation is different, the step is already done, or the "
            "prospect has said no. Don't swap a style that works for a memorised script. If "
            "the moment is missing context, keep that in mind."
        ),
        checklist=(
            "Did I replay the moment in full?",
            "Does this change fit what the call needed?",
            "Could someone else notice it?",
            "Does it respect what the prospect said?",
        ),
        source=SOURCE,
        own_call=moment,
        next_call_connection=mission.behavior,
    )
