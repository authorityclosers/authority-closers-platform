"""Text teaching grounded in the owner's binding Coaching specification.

Do not silently adopt an unapproved training/profile candidate as knowledge.
The impact/discovery framework is explicitly taught in Coaching §3. Other
skills use the spec's own-call comparison method and the source-bound mission;
they do not acquire an invented subject-specific framework.
"""

from ac_platform.coaching.contracts import Mission, Moment, TextLesson

SOURCE = "Owner's Sales Xray specification, 9 Oct 2026 · Coaching §3 and §5.6"


def lesson_for(skill_id: str, moment: Moment, mission: Mission) -> TextLesson:
    impact = skill_id in {"discovery_deep_understanding", "problem_impact_desire"}
    if impact:
        return TextLesson(
            title="Understand the impact before choosing a solution",
            quick_idea=(
                "A problem statement is a starting point. Understand what the problem is causing "
                "and what the prospect wants to change before choosing a solution. More questions "
                "are useful only when they create clarity."
            ),
            framework=("Problem", "Impact", "Desired outcome", "Relevant solution"),
            why_it_matters=(
                "A recommendation is easier to understand when it connects to the prospect's "
                "actual situation. Use the evidence below to check what was already clear, what "
                "remained unanswered, and whether another question would have helped."
            ),
            good_looks_like=(
                "Explore a real consequence in the prospect's own terms: time, effort, money, "
                "risk or another meaningful effect. Confirm the desired outcome. Preserve "
                "uncertainty rather than filling in an amount, motivation or commitment."
            ),
            better_direction=mission.behavior,
            example_wording=(
                "What does that problem affect in your day-to-day work?",
                "What would you want to change about that?",
            ),
            when_to_use=(
                "Use this thinking guide when the prospect raises a meaningful problem and its "
                "consequences or desired outcome are still unclear. Check earlier answers first."
            ),
            when_not=(
                "Do not keep digging after the point is clear, repeat a question already answered, "
                "manufacture pain, or continue after a genuine refusal. A call can return to "
                "discovery when new information appears; this is not a fixed sequence."
            ),
            checklist=(
                "What has the prospect actually said?",
                "Is the consequence clear, or still unknown?",
                "What outcome do they want?",
                "Would the next question add useful clarity?",
            ),
            source=SOURCE,
            own_call=moment,
            next_call_connection=mission.behavior,
        )
    return TextLesson(
        title="Turn this call moment into one useful change",
        quick_idea=(
            "Start with the actual situation, then choose the smallest useful alternative. "
            "A framework should help your thinking while preserving your own language and style. "
            "This lesson uses your report's provisional recommendation; you can challenge it."
        ),
        framework=(
            "Replay the moment",
            "Check the purpose",
            "Choose one response",
            "Check the result",
        ),
        why_it_matters=moment.observation,
        good_looks_like=(
            "Listen to the evidence in context, including what the prospect already answered. "
            "Describe the change in observable terms. Practise it in words that feel natural "
            "to you, then try it only when a comparable situation gives you a real opportunity."
        ),
        better_direction=mission.behavior,
        example_wording=(),
        when_to_use=mission.context,
        when_not=(
            "Do not apply a correction when the situation is different, the step is already "
            "complete, or the prospect has declined it. Do not replace an effective personal "
            "style with a memorized script. If the evidence misses context, keep that uncertainty."
        ),
        checklist=(
            "Did I replay the moment in context?",
            "Is this change relevant to the conversation's purpose?",
            "Can another person observe the behavior?",
            "Does the response respect the prospect's boundary?",
        ),
        source=SOURCE,
        own_call=moment,
        next_call_connection=mission.behavior,
    )
